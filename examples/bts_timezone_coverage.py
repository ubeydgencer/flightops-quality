"""Describe timezone endpoint-offset coverage in an original accepted batch.

This helper performs no source IO or normalization. Offset observations use
already resolved UTC instants and the caller's IANA timezone mapping. They are
derived coverage evidence, not independent validation of absolute UTC dates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flightops_quality.models import BatchReport


def _timezone_map(airport_timezones: Mapping[str, str]) -> dict:
    if not isinstance(airport_timezones, Mapping):
        raise ValueError("Airport timezones must be a mapping")
    result, cache = {}, {}
    for airport, name in airport_timezones.items():
        if not isinstance(airport, str) or not airport.strip() or not isinstance(name, str):
            raise ValueError("Airport timezone entries require airport and IANA zone strings")
        if name not in cache:
            try:
                cache[name] = ZoneInfo(name)
            except (ValueError, ZoneInfoNotFoundError) as exc:
                raise ValueError(f"Unknown IANA timezone for airport {airport}") from exc
        result[airport] = cache[name]
    return result


def _instant(value, label):
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be an aware datetime")
    try:
        if value.utcoffset() is None:
            raise ValueError(f"{label} must identify an instant")
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must identify a representable UTC instant") from exc


def _window(start, end, label):
    start, end = _instant(start, f"{label} start"), _instant(end, f"{label} end")
    if start is None or end is None:
        return None
    if end < start or (label == "scheduled" and end == start):
        raise ValueError(f"{label} endpoints are not in chronological order")
    return start, end


def _changes(start, end, zones):
    changes = []
    for zone in zones:
        try:
            local_start, local_end = start.astimezone(zone), end.astimezone(zone)
            offset_start = int(local_start.utcoffset().total_seconds())
            offset_end = int(local_end.utcoffset().total_seconds())
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Window endpoints cannot be represented in {zone.key}") from exc
        if offset_start != offset_end:
            changes.append({
                "timezone": zone.key,
                "offset_start_seconds": offset_start,
                "offset_end_seconds": offset_end,
                "change_seconds": offset_end - offset_start,
                "local_start": local_start.isoformat(),
                "local_end": local_end.isoformat(),
            })
    return changes


def timezone_offset_coverage(report: BatchReport, airport_timezones: Mapping[str, str]) -> dict:
    """Compare each airport zone's own offsets at each resolved window endpoint.

    Scheduled windows include every accepted unique flight. Actual windows use
    only noncancelled, nondiverted accepted unique flights. A shared IANA zone is
    counted once within a window. Missing endpoints are excluded; unusable maps,
    naive timestamps and invalid chronology are errors rather than guesses.
    """
    if not isinstance(report, BatchReport):
        raise ValueError("Timezone coverage requires an original BatchReport")
    airport_zones = _timezone_map(airport_timezones)
    result = {name: {"population_rows": 0, "checked": 0,
                     "excluded_counts": {"missing_timestamps": 0},
                     "offset_change_rows": 0, "zone_change_observations": 0,
                     "examples": []}
              for name in ("scheduled", "actual")}
    for record in report.accepted:
        leg = record.flight
        try:
            zones_by_name = {airport_zones[airport].key: airport_zones[airport]
                             for airport in (leg.origin, leg.destination)}
        except KeyError as exc:
            raise ValueError(f"Accepted flight airport lacks a timezone mapping: {exc.args[0]}") from exc
        zones = [zones_by_name[name] for name in sorted(zones_by_name)]
        windows = [("scheduled", leg.sobt, leg.sibt)]
        if not leg.cancelled and not leg.diverted:
            windows.append(("actual", leg.aobt, leg.aibt))
        for label, start, end in windows:
            item = result[label]
            item["population_rows"] += 1
            window = _window(start, end, label)
            if window is None:
                item["excluded_counts"]["missing_timestamps"] += 1
                continue
            start, end = window
            changes = _changes(start, end, zones)
            item["checked"] += 1
            item["zone_change_observations"] += len(changes)
            if changes:
                item["offset_change_rows"] += 1
                if len(item["examples"]) < 10:
                    item["examples"].append({
                        "source": leg.source, "record_id": leg.record_id,
                        "source_row_number": record.row_number,
                        "service_date": leg.service_date.isoformat(),
                        "origin": leg.origin, "destination": leg.destination,
                        "route": f"{leg.origin}-{leg.destination}",
                        "window_start_utc": start.isoformat(), "window_end_utc": end.isoformat(),
                        "changes": changes,
                    })
    for item in result.values():
        item["reconciled"] = (item["checked"] + sum(item["excluded_counts"].values())
                              == item["population_rows"])
        if not item["reconciled"]:
            raise ValueError("Timezone endpoint coverage failed to reconcile")
    return {
        "policy": {
            "population": "Original batch accepted unique flights only; quarantined rows and exact repeats are excluded.",
            "scheduled": "Resolved sobt-to-sibt windows for every accepted unique flight, including cancellation and diversion.",
            "actual": "Resolved aobt-to-aibt windows for noncancelled, nondiverted accepted unique flights only.",
            "comparison": "Each unique origin/destination IANA zone is compared with itself at both UTC endpoints; airport zones are never compared to each other.",
            "absolute_utc_validation": False,
            "interpretation": "A derived endpoint UTC-offset difference is coverage evidence, not independent absolute UTC validation and not necessarily a DST change.",
            "limitations": "Only the two endpoints are compared. Two compensating offset changes inside a window cannot be detected.",
            "resolution": "Use already resolved aware instants; do not guess a local date, midnight policy or DST fold.",
            "units": "offset_change_rows counts flight windows; zone_change_observations counts changed unique zones within those windows. Examples show at most ten windows per population.",
        },
        **result,
    }
