"""Gate/runway chronology and conservative operational metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from .models import FlightLeg, Issue

TIMESTAMPS = ("sobt", "sibt", "aobt", "atot", "aldt", "aibt")


def _instant(value: Optional[datetime]) -> Optional[datetime]:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        return value.astimezone(timezone.utc) if value.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def validate_leg(leg: FlightLeg) -> Tuple[Issue, ...]:
    issues = []
    instants = {}
    for name in TIMESTAMPS:
        value = getattr(leg, name)
        instant = _instant(value)
        if value is not None and instant is None:
            issues.append(Issue("TIME_NOT_AWARE", "error", (name,), "Canonical timestamps must identify an instant."))
        instants[name] = instant
    if leg.sobt is None or leg.sibt is None:
        issues.append(Issue("SCHEDULE_INCOMPLETE", "warning", ("sobt", "sibt"), "Scheduled gate timestamps are incomplete."))
    if instants["sobt"] is not None and instants["sibt"] is not None:
        if instants["sibt"] <= instants["sobt"]:
            issues.append(Issue("SCHEDULE_ORDER", "error", ("sobt", "sibt"), "Scheduled arrival must follow scheduled departure."))
    present = [(name, instants[name]) for name in ("aobt", "atot", "aldt", "aibt") if instants[name] is not None]
    for (left_name, left), (right_name, right) in zip(present, present[1:]):
        if right < left:
            issues.append(Issue("ACTUAL_ORDER", "error", (left_name, right_name), "Actual gate/runway milestones are out of chronological order."))
    if not leg.cancelled and not leg.diverted and (leg.aobt is None or leg.aibt is None):
        issues.append(Issue("ACTUAL_INCOMPLETE", "warning", ("aobt", "aibt"), "Normal-flight actual gate timestamps are incomplete; affected metrics remain null."))
    return tuple(issues)


def _minutes(start: Optional[datetime], end: Optional[datetime], *, signed: bool = False) -> Optional[float]:
    start, end = _instant(start), _instant(end)
    if start is None or end is None:
        return None
    value = (end - start).total_seconds() / 60
    return value if signed or value >= 0 else None


def flight_metrics(leg: FlightLeg) -> dict:
    result = dict.fromkeys(("departure_delay_minutes", "arrival_delay_minutes", "block_minutes",
                            "taxi_out_minutes", "taxi_in_minutes", "airborne_minutes"))
    if leg.cancelled:
        return result
    result["departure_delay_minutes"] = _minutes(leg.sobt, leg.aobt, signed=True)
    result["taxi_out_minutes"] = _minutes(leg.aobt, leg.atot)
    if not leg.diverted:
        result["arrival_delay_minutes"] = _minutes(leg.sibt, leg.aibt, signed=True)
        result["block_minutes"] = _minutes(leg.aobt, leg.aibt)
        result["taxi_in_minutes"] = _minutes(leg.aldt, leg.aibt)
        result["airborne_minutes"] = _minutes(leg.atot, leg.aldt)
    return result


def turnaround_minutes(inbound: FlightLeg, outbound: FlightLeg) -> float:
    if inbound.cancelled or outbound.cancelled or inbound.diverted or outbound.diverted:
        raise ValueError("Turnaround requires two normal flights with known airport semantics")
    if not inbound.aircraft_registration or inbound.aircraft_registration != outbound.aircraft_registration:
        raise ValueError("Turnaround requires the same known aircraft registration")
    if not inbound.destination or inbound.destination != outbound.origin:
        raise ValueError("Turnaround requires a matching connecting airport")
    if any(issue.severity == "error" for leg in (inbound, outbound) for issue in validate_leg(leg)):
        raise ValueError("Turnaround pair contains invalid chronology or timestamps")
    result = _minutes(inbound.aibt, outbound.aobt)
    if result is None:
        raise ValueError("Turnaround requires ordered, aware actual arrival/departure gate timestamps")
    return result
