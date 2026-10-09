"""Opt-in batch quality gates with explicit populations and inclusive limits."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .analytics import summarize
from .models import BatchReport


@dataclass(frozen=True)
class QualityPolicy:
    """Consumer-selected requirements; no universal aviation limits are assumed."""

    min_arrival_coverage_percent: Optional[float] = None
    min_otp_eligible_flights: Optional[int] = None
    max_quarantine_rate_percent: Optional[float] = None

    def __post_init__(self) -> None:
        for name in ("min_arrival_coverage_percent", "max_quarantine_rate_percent"):
            value = getattr(self, name)
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not 0 <= value <= 100
                    or (isinstance(value, float) and not math.isfinite(value))):
                raise ValueError(f"{name} must be a finite number between 0 and 100")
        count = self.min_otp_eligible_flights
        if count is not None and (isinstance(count, bool) or not isinstance(count, int)
                                  or not 0 <= count <= 2**63 - 1):
            raise ValueError("min_otp_eligible_flights must be an integer from 0 to 2**63-1")

    def to_dict(self) -> dict:
        return {
            "min_arrival_coverage_percent": self.min_arrival_coverage_percent,
            "min_otp_eligible_flights": self.min_otp_eligible_flights,
            "max_quarantine_rate_percent": self.max_quarantine_rate_percent,
        }


def evaluate_quality(report: BatchReport, policy: Optional[QualityPolicy] = None) -> dict:
    """Evaluate configured gates, failing percentage gates with no observations.

    Exact repeats do not improve a quarantine-rate denominator. Conflicting
    identity groups retain every quarantined member, including their repeats.
    """
    if not isinstance(report, BatchReport):
        raise ValueError("report must be a BatchReport")
    if policy is None:
        policy = QualityPolicy()
    if not isinstance(policy, QualityPolicy):
        raise ValueError("policy must be a QualityPolicy or None")
    summary = summarize(report)
    otp = summary["arrival_otp_15_completed"]
    eligible = otp["eligible"]
    normal_population = eligible + otp["excluded_missing_arrival_delay"]
    counts = summary["counts"]
    quarantine_population = counts["accepted"] + counts["quarantined"]
    measurements = {
        "arrival_coverage_percent": {
            "value": 100 * eligible / normal_population if normal_population else None,
            "numerator": eligible,
            "denominator": normal_population,
            "population": "Accepted unique, non-cancelled, non-diverted flights.",
        },
        "otp_eligible_flights": {
            "value": eligible,
            "population": "Accepted unique, non-cancelled, non-diverted flights with valid arrival delay.",
        },
        "quarantine_rate_percent": {
            "value": 100 * counts["quarantined"] / quarantine_population if quarantine_population else None,
            "numerator": counts["quarantined"],
            "denominator": quarantine_population,
            "population": "Accepted plus quarantined records; exact repeats excluded; every conflict-group member is quarantined.",
        },
    }
    checks = []
    for field, metric, operator in (
        ("min_arrival_coverage_percent", "arrival_coverage_percent", ">="),
        ("min_otp_eligible_flights", "otp_eligible_flights", ">="),
        ("max_quarantine_rate_percent", "quarantine_rate_percent", "<="),
    ):
        threshold = getattr(policy, field)
        if threshold is None:
            continue
        observed = measurements[metric]["value"]
        if observed is None:
            passed = False
            reason = "The measurement population is empty; an unobserved percentage cannot satisfy a configured threshold."
        else:
            passed = observed >= threshold if operator == ">=" else observed <= threshold
            reason = ("Observed value satisfies the inclusive threshold." if passed
                      else "Observed value does not satisfy the inclusive threshold.")
        checks.append({
            "metric": metric,
            "operator": operator,
            "threshold": threshold,
            "observed": observed,
            "passed": passed,
            "reason": reason,
        })
    status = "not_configured" if not checks else ("passed" if all(c["passed"] for c in checks) else "failed")
    return {"status": status, "policy": policy.to_dict(), "measurements": measurements, "checks": checks}
