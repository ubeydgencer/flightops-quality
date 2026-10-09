"""Metrics with explicit populations; never turn missing observations into zero."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .models import BatchReport
from .rules import flight_metrics


def summarize(report: BatchReport) -> dict[str, Any]:
    """Summarize accepted unique records. Quarantine and duplicates are excluded."""
    cancelled = diverted = eligible = on_time = missing_arrival = 0
    issues: Counter = Counter()
    for result in (*report.accepted, *report.quarantined, *report.duplicates):
        issues.update(issue.code for issue in result.issues)
    for result in report.accepted:
        leg = result.flight
        if leg is None:
            raise ValueError("Accepted records must contain a normalized flight")
        cancelled += int(leg.cancelled)
        diverted += int(leg.diverted)
        if leg.cancelled or leg.diverted:
            continue
        delay = flight_metrics(leg)["arrival_delay_minutes"]
        if delay is None:
            missing_arrival += 1
            continue
        eligible += 1
        on_time += int(delay < 15)
    population = len(report.accepted)
    return {
        "counts": report.counts,
        "issue_counts": dict(sorted(issues.items())),
        "accepted_population": {
            "flights": population,
            "cancelled": cancelled,
            "diverted": diverted,
            "cancellation_rate_percent": 100 * cancelled / population if population else None,
            "diversion_rate_percent": 100 * diverted / population if population else None,
        },
        "arrival_otp_15_completed": {
            "eligible": eligible,
            "coverage_population": eligible + missing_arrival,
            "coverage_percent": (
                100 * eligible / (eligible + missing_arrival)
                if eligible + missing_arrival else None
            ),
            "on_time": on_time,
            "late": eligible - on_time,
            "percent": 100 * on_time / eligible if eligible else None,
            "excluded_cancelled_or_diverted": sum(
                bool(r.flight.cancelled or r.flight.diverted) for r in report.accepted
            ),
            "excluded_missing_arrival_delay": missing_arrival,
            "policy": "Accepted unique, non-cancelled, non-diverted flights with valid arrival delay; delay < 15 minutes.",
        },
    }
