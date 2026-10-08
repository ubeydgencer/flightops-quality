"""Normalize a documented ISO mapping; preserve every raw source field."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Mapping

from ..models import FlightLeg, Issue, RecordResult
from ..rules import validate_leg
from ..time import resolve_timestamp

REQUIRED = ("source", "record_id", "carrier", "flight_number", "origin", "destination")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_record(row: Mapping, *, row_number: int = 1) -> RecordResult:
    if not isinstance(row, Mapping):
        raise ValueError("Canonical input must be a JSON-compatible mapping")
    raw = dict(row)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError("Raw input must have string keys")
    try:
        json.dumps(raw, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Raw input must contain finite JSON-compatible values") from exc
    issues = []
    values = {}
    for name in REQUIRED:
        value = row.get(name)
        if not isinstance(value, str) or not value.strip():
            issues.append(Issue("FIELD_REQUIRED", "error", (name,), "Expected a nonempty identity string."))
        else:
            values[name] = value.strip()
    try:
        service_date = row.get("service_date")
        if not isinstance(service_date, str) or not DATE_PATTERN.fullmatch(service_date):
            raise ValueError
        values["service_date"] = date.fromisoformat(service_date)
    except ValueError:
        issues.append(Issue("DATE_INVALID", "error", ("service_date",), "Expected a valid YYYY-MM-DD service date."))
    if len(values) != len(REQUIRED) + 1:
        return RecordResult(None, tuple(issues), raw, row_number)
    for name in ("cancelled", "diverted"):
        value = row.get(name, False)
        if isinstance(value, bool):
            values[name] = value
        elif value in (0, 1) and isinstance(value, int):
            values[name] = bool(value)
        elif isinstance(value, str) and value.strip().lower() in {"", "0", "1", "false", "true"}:
            values[name] = value.strip().lower() in {"1", "true"}
        else:
            values[name] = False
            issues.append(Issue("FLAG_INVALID", "error", (name,), "Expected boolean or 0/1/true/false flag."))
    tail = row.get("aircraft_registration")
    if tail is not None and not isinstance(tail, str):
        issues.append(Issue("FIELD_INVALID", "error", ("aircraft_registration",), "Aircraft registration must be a string or null."))
        tail = None
    values["aircraft_registration"] = tail.strip() or None if tail is not None else None
    provenance = {}
    for name in ("sobt", "sibt", "aobt", "aibt", "atot", "aldt"):
        value = row.get(name)
        if isinstance(value, str):
            value = value.strip() or None
        zone_field = "origin_timezone" if name in {"sobt", "aobt", "atot"} else "destination_timezone"
        fold = row.get(name + "_fold")
        if fold == "":
            fold = None
        if isinstance(fold, str) and fold in {"0", "1"}:
            fold = int(fold)
        result = resolve_timestamp(value, row.get(zone_field), fold)
        values[name] = result.value
        issues.extend(Issue(i.code, i.severity, (name,), i.message) for i in result.issues)
        if result.value is not None:
            # Offset-bearing strings identify the instant without a timezone lookup.
            naive = isinstance(value, str) and not (value.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", value))
            inputs = [name]
            if naive:
                inputs.append(zone_field)
                if fold is not None:
                    inputs.append(name + "_fold")
            provenance[name] = tuple(inputs)
    leg = FlightLeg(**values, provenance=provenance)
    return RecordResult(leg, tuple(issues) + validate_leg(leg), raw, row_number)
