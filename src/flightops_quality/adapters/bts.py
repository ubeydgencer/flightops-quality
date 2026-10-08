"""Bounded BTS Reporting Carrier adapter with explicit timestamp derivation.

Identity policy: JSON tuple of FlightDate, operating/reporting carrier ID (or code),
flight number, origin/destination AirportID (or code), and the raw CRSDepTime.
Tail number is deliberately not part of identity. Scheduled departure 2400 needs
an explicit start/end-of-FlightDate policy; other clocks are comparisons, not date
anchors. Validate the policy against the dated provider release used.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import FlightLeg, Issue, RecordResult
from ..rules import validate_leg
from ..time import resolve_timestamp

CLOCK_FIELDS = ("CRSDepTime", "CRSArrTime", "DepTime", "ArrTime", "WheelsOff", "WheelsOn")
DURATION_FIELDS = ("CRSElapsedTime", "DepDelay", "ActualElapsedTime", "TaxiOut", "TaxiIn", "AirTime", "ArrDelay")


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _integer(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Expected a whole finite number")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("Expected a whole finite number") from exc
    if not number.is_finite() or number != number.to_integral_value() or abs(number) > 10**10:
        raise ValueError("Expected a bounded whole finite number")
    return int(number)


def parse_bts_clock(value) -> Optional[int]:
    """Return minute of day 0..1440, with 2400 represented as 1440."""
    if _blank(value):
        return None
    clock = _integer(value)
    if clock == 2400:
        return 1440
    if clock < 0 or clock >= 2400 or clock % 100 >= 60:
        raise ValueError("Expected HHMM from 0000..2359 or 2400")
    return clock // 100 * 60 + clock % 100


def normalize_bts_row(row: Mapping, airport_timezones: Mapping[str, str], *,
                      record_id: Optional[str] = None, source: str = "bts", row_number: int = 1,
                      departure_fold: Optional[int] = None,
                      midnight_policy: Optional[str] = None) -> RecordResult:
    if midnight_policy not in (None, "start", "end"):
        raise ValueError("midnight_policy must be None, 'start', or 'end'")
    if not isinstance(row, Mapping) or not isinstance(airport_timezones, Mapping):
        raise ValueError("BTS row and airport timezones must be mappings")
    raw = dict(row)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError("Raw input must have string keys")
    try:
        json.dumps(raw, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Raw input must contain finite JSON-compatible values") from exc
    issues = []

    def finding(code, severity, fields, message):
        issues.append(Issue(code, severity, tuple(fields), message))

    def first(*names):
        for name in names:
            value = row.get(name)
            if _blank(value):
                continue
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                finding("FIELD_INVALID", "error", (name,), "Expected a scalar identity value.")
                return ""
            return str(value).strip()
        return ""

    carrier = first("Operating_Airline", "Reporting_Airline")
    carrier_id = first("DOT_ID_Operating_Airline", "DOT_ID_Reporting_Airline") or carrier
    number = first("Flight_Number_Operating_Airline", "Flight_Number_Reporting_Airline")
    origin, destination = first("Origin"), first("Dest")
    day = first("FlightDate")
    service_date = None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError
        service_date = date.fromisoformat(day)
    except ValueError:
        finding("DATE_INVALID", "error", ("FlightDate",), "Expected a valid YYYY-MM-DD flight service date.")
    for value, field in ((source, "source"), (carrier, "Operating_Airline/Reporting_Airline"),
                         (number, "Flight_Number"), (origin, "Origin"), (destination, "Dest")):
        if not isinstance(value, str) or not value.strip():
            finding("FIELD_REQUIRED", "error", (field,), "Required flight identity field is missing.")
    if _blank(row.get("CRSDepTime")):
        finding("FIELD_REQUIRED", "error", ("CRSDepTime",), "Scheduled departure clock is required for BTS identity and date anchoring.")
    if record_id is None:
        record_id = json.dumps([day, carrier_id, number, first("OriginAirportID") or origin,
                                first("DestAirportID") or destination, first("CRSDepTime")], separators=(",", ":"))
    elif not isinstance(record_id, str) or not record_id.strip():
        finding("FIELD_REQUIRED", "error", ("record_id",), "Caller record_id must be a nonempty string.")
    if service_date is None or any(i.severity == "error" for i in issues):
        return RecordResult(None, tuple(issues), raw, row_number)

    clocks, durations, flags = {}, {}, {}
    for field in CLOCK_FIELDS:
        try:
            clocks[field] = parse_bts_clock(row.get(field))
        except ValueError:
            clocks[field] = None
            finding("BTS_CLOCK_INVALID", "error", (field,), "Expected integral HHMM (0000..2359 or midnight 2400).")
    for field in DURATION_FIELDS:
        try:
            value = None if _blank(row.get(field)) else _integer(row[field])
            if value is not None and field not in {"DepDelay", "ArrDelay"} and value < 0:
                raise ValueError
            durations[field] = value
        except ValueError:
            durations[field] = None
            finding("BTS_NUMBER_INVALID", "error", (field,), "Expected finite whole minutes, nonnegative except signed delays.")
    for field in ("Cancelled", "Diverted"):
        try:
            value = _integer(row.get(field))
            if value not in (0, 1):
                raise ValueError
            flags[field] = bool(value)
        except ValueError:
            flags[field] = False
            finding("FLAG_INVALID", "error", (field,), "Expected explicit 0 or 1 BTS status flag.")
    zones = {}
    for airport, field in ((origin, "Origin"), (destination, "Dest")):
        try:
            zones[field] = ZoneInfo(airport_timezones[airport])
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
            zones[field] = None
            finding("TIME_ZONE_UNKNOWN", "error", (field,), "Airport lacks a usable caller-supplied IANA timezone.")
    times = dict.fromkeys(("sobt", "sibt", "aobt", "aibt", "atot", "aldt"))
    provenance = {}

    def shift(anchor, minutes, target, inputs):
        if anchor is None or minutes is None:
            return None
        try:
            result = anchor + timedelta(minutes=minutes)
        except (ValueError, OverflowError):
            finding("BTS_TIME_RANGE", "error", inputs, "Derived timestamp is outside the supported datetime range.")
            return None
        times[target] = result
        provenance[target] = tuple(inputs)
        return result

    def compare_clock(timestamp, field, airport_field):
        if timestamp is None or clocks[field] is None or zones[airport_field] is None:
            return
        try:
            local = timestamp.astimezone(zones[airport_field])
        except (ValueError, OverflowError):
            finding("BTS_TIME_RANGE", "error", (field,), "Derived UTC timestamp cannot be represented locally.")
            return
        if local.hour * 60 + local.minute != clocks[field] % 1440:
            finding("BTS_CLOCK_MISMATCH", "error", (field,), "Local clock disagrees with the timestamp derived from signed delay/elapsed evidence.")

    if clocks["CRSDepTime"] is not None and zones["Origin"] is not None:
        try:
            anchor_minutes = clocks["CRSDepTime"]
            if anchor_minutes == 1440 and midnight_policy is None:
                finding("BTS_MIDNIGHT_UNRESOLVED", "error", ("FlightDate", "CRSDepTime"),
                        "Scheduled 2400 needs an explicit start/end-of-service-date policy verified for the source release.")
            else:
                if anchor_minutes == 1440 and midnight_policy == "start":
                    anchor_minutes = 0
                local = datetime.combine(service_date, datetime.min.time()) + timedelta(minutes=anchor_minutes)
                resolved = resolve_timestamp(local, zones["Origin"].key, departure_fold)
                issues.extend(Issue(i.code, i.severity, ("FlightDate", "CRSDepTime", "Origin"), i.message) for i in resolved.issues)
                times["sobt"] = resolved.value
                if resolved.value is not None:
                    provenance["sobt"] = ("FlightDate", "CRSDepTime", "Origin", "airport_timezones")
                    if clocks["CRSDepTime"] == 1440:
                        provenance["sobt"] += ("midnight_policy",)
                    if departure_fold is not None:
                        provenance["sobt"] += ("departure_fold",)
        except (ValueError, OverflowError):
            finding("BTS_TIME_RANGE", "error", ("FlightDate", "CRSDepTime"), "Departure anchor is outside the supported datetime range.")
    shift(times["sobt"], durations["CRSElapsedTime"], "sibt", ("FlightDate", "CRSDepTime", "Origin", "CRSElapsedTime", "airport_timezones"))
    compare_clock(times["sibt"], "CRSArrTime", "Dest")
    if times["sibt"] is None:
        finding("BTS_TIME_UNRESOLVED", "warning", ("CRSArrTime", "CRSElapsedTime"), "Scheduled arrival date is unresolved; a local clock alone is insufficient.")
    # Actual clock dates come from signed delay, never a +/- one-day clock heuristic.
    has_departure_evidence = clocks["DepTime"] is not None or durations["DepDelay"] is not None
    if not flags["Cancelled"] or has_departure_evidence:
        shift(times["sobt"], durations["DepDelay"], "aobt", ("FlightDate", "CRSDepTime", "Origin", "DepDelay", "airport_timezones"))
        compare_clock(times["aobt"], "DepTime", "Origin")
        if times["aobt"] is None and has_departure_evidence:
            finding("BTS_TIME_UNRESOLVED", "warning", ("DepTime", "DepDelay"), "Actual departure date needs a resolved schedule anchor and signed departure delay.")
    shift(times["aobt"], durations["TaxiOut"], "atot", ("aobt", "TaxiOut"))
    compare_clock(times["atot"], "WheelsOff", "Origin")
    if not flags["Cancelled"] and not flags["Diverted"]:
        shift(times["aobt"], durations["ActualElapsedTime"], "aibt", ("aobt", "ActualElapsedTime"))
        compare_clock(times["aibt"], "ArrTime", "Dest")
        shift(times["aibt"], -durations["TaxiIn"] if durations["TaxiIn"] is not None else None,
              "aldt", ("aibt", "TaxiIn"))
        compare_clock(times["aldt"], "WheelsOn", "Dest")
        if times["aibt"] is None and clocks["ArrTime"] is not None:
            finding("BTS_TIME_UNRESOLVED", "warning", ("ArrTime", "ActualElapsedTime"), "Actual arrival date needs actual departure and elapsed time evidence.")
        if times["sibt"] is not None and times["aibt"] is not None and durations["ArrDelay"] is not None:
            observed = (times["aibt"] - times["sibt"]).total_seconds() / 60
            if observed != durations["ArrDelay"]:
                finding("BTS_DURATION_MISMATCH", "error", ("ArrDelay", "ActualElapsedTime", "DepDelay", "CRSElapsedTime"), "Reported arrival delay disagrees with the derived gate timestamps.")
        if times["atot"] is not None and times["aldt"] is not None and durations["AirTime"] is not None:
            observed = (times["aldt"] - times["atot"]).total_seconds() / 60
            if observed != durations["AirTime"]:
                finding("BTS_DURATION_MISMATCH", "error", ("AirTime", "TaxiOut", "TaxiIn", "ActualElapsedTime"), "Reported airborne minutes disagree with the derived runway timestamps.")
    leg = FlightLeg(source.strip(), record_id.strip(), service_date, carrier, number, origin, destination,
                    aircraft_registration=first("Tail_Number") or None,
                    cancelled=flags["Cancelled"], diverted=flags["Diverted"],
                    **times, provenance=provenance)
    return RecordResult(leg, tuple(issues) + validate_leg(leg), raw, row_number)
