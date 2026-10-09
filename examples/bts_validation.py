"""Read-only, JSON-ready BTS cohort validation; callers own source IO and bounds.

Original observations form one batch. A separate probe withholds ArrDelay and
AirTime, then compares their reported values to duration-derived predictions.
This checks source-field consistency, not independently known absolute UTC dates.
No midnight anchor or DST fold is guessed.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal, DecimalException
from typing import Iterable, Mapping

from bts_timezone_coverage import timezone_offset_coverage

from flightops_quality.adapters.bts import normalize_bts_row
from flightops_quality.analytics import summarize
from flightops_quality.batch import analyze_results
from flightops_quality.rules import flight_metrics

CLOCK_FIELDS = ("CRSDepTime", "CRSArrTime", "DepTime", "ArrTime", "WheelsOff", "WheelsOn")
DURATION_FIELDS = ("CRSElapsedTime", "DepDelay", "ActualElapsedTime", "TaxiOut", "TaxiIn", "AirTime", "ArrDelay")
UNRESOLVED_CODES = {
    "BTS_MIDNIGHT_UNRESOLVED", "TIME_AMBIGUOUS", "TIME_NONEXISTENT",
    "TIME_ZONE_UNKNOWN", "TIME_ZONE_REQUIRED", "BTS_TIME_UNRESOLVED",
    "BTS_TIME_RANGE", "SCHEDULE_INCOMPLETE", "ACTUAL_INCOMPLETE",
}
HOLDOUTS = {"ArrDelay": "arrival_delay_minutes", "AirTime": "airborne_minutes"}
DIAGNOSTIC_FIELDS = (
    "FlightDate", "Reporting_Airline", "Operating_Airline", "DOT_ID_Reporting_Airline",
    "DOT_ID_Operating_Airline", "Flight_Number_Reporting_Airline", "Flight_Number_Operating_Airline",
    "Origin", "OriginAirportID", "OriginAirportSeqID", "Dest", "DestAirportID", "DestAirportSeqID",
    "Tail_Number", "Cancelled", "Diverted", *CLOCK_FIELDS, *DURATION_FIELDS,
)


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _whole_minute(value, *, signed: bool = False):
    """Independent finite integral parser; never substitutes clamped delay fields."""
    if _blank(value):
        return None, "missing"
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None, "invalid"
    text = str(value).strip()
    if len(text) > 128:
        return None, "invalid"
    try:
        number = Decimal(text)
        if (not number.is_finite() or number.copy_abs() > 10**10
                or number != number.to_integral_value() or (number < 0 and not signed)):
            return None, "invalid"
        return int(number), None
    except (DecimalException, ValueError, OverflowError):
        return None, "invalid"


def _status(value):
    number, reason = _whole_minute(value)
    return str(number) if reason is None and number in (0, 1) else "invalid"


def _source_arrivals(records):
    """Parse original signed ArrDelay without consulting derived timestamps."""
    population = eligible = on_time = late = 0
    excluded = Counter()
    for record in records:
        raw = record.raw
        cancelled, diverted = _status(raw.get("Cancelled")), _status(raw.get("Diverted"))
        if "invalid" in (cancelled, diverted):
            excluded["invalid_status"] += 1
            continue
        if "1" in (cancelled, diverted):
            excluded["cancelled_or_diverted"] += 1
            continue
        population += 1
        delay, reason = _whole_minute(raw.get("ArrDelay"), signed=True)
        if reason:
            excluded[f"{reason}_arrival_delay"] += 1
            continue
        eligible += 1
        on_time += int(delay < 15)
        late += int(delay >= 15)
    return {
        "input_rows": len(records), "coverage_population": population, "eligible": eligible,
        "on_time": on_time, "late": late,
        "percent": 100 * on_time / eligible if eligible else None,
        "coverage_percent": 100 * eligible / population if population else None,
        "excluded_counts": dict(sorted(excluded.items())),
    }


def _probe_error_reason(probe):
    errors = {issue.code for issue in probe.issues if issue.severity == "error"}
    for code, reason in (
        ("BTS_MIDNIGHT_UNRESOLVED", "midnight_policy_unresolved"),
        ("TIME_AMBIGUOUS", "dst_ambiguous"), ("TIME_NONEXISTENT", "dst_nonexistent"),
        ("TIME_ZONE_UNKNOWN", "timezone_unknown"), ("TIME_ZONE_REQUIRED", "timezone_unknown"),
        ("DATE_INVALID", "invalid_service_date"), ("BTS_TIME_RANGE", "timestamp_range"),
        ("SCHEDULE_ORDER", "probe_chronology_error"), ("ACTUAL_ORDER", "probe_chronology_error"),
        ("BTS_CLOCK_MISMATCH", "probe_clock_mismatch"),
        ("BTS_CLOCK_INVALID", "invalid_derivation_input"),
        ("BTS_NUMBER_INVALID", "invalid_derivation_input"),
        ("FIELD_INVALID", "invalid_identity"), ("FIELD_REQUIRED", "invalid_identity"),
    ):
        if code in errors:
            return reason
    return "probe_validation_error" if errors else None


def _airport_observation(airports, raw, role, code):
    item = airports.setdefault(code, {"airport_ids": set(), "airport_sequence_ids": set(),
                                      "observations": Counter(), "missing_field_counts": Counter(),
                                      "invalid_field_counts": Counter()})
    item["observations"][role] += 1
    for suffix, destination in (("AirportID", "airport_ids"), ("AirportSeqID", "airport_sequence_ids")):
        field = role + suffix
        number, reason = _whole_minute(raw.get(field))
        if reason is None:
            item[destination].add(str(number))
        else:
            item[f"{reason}_field_counts"][field] += 1


def validate_rows(rows: Iterable[tuple[int, Mapping]], airport_timezones: Mapping[str, str]) -> dict:
    """Validate every supplied row without source IO, sampling or status filters.

    Each hold-out partitions the cohort into checked or one exclusion reason.
    Invalid/missing targets and cancelled/diverted flights are not compared.
    Missing clocks remain visible but do not prevent comparison when sufficient
    signed-delay/elapsed evidence resolves the prediction. Callers must bound
    overall payload and record counts and record their source/scope manifest.
    """
    originals = []
    issue_examples = []
    issues, unresolved, missing_fields, routes, dates = (Counter() for _ in range(5))
    airports = {}
    invalid_dates = 0
    status_counts = {"Cancelled": Counter({"0": 0, "1": 0, "invalid": 0}),
                     "Diverted": Counter({"0": 0, "1": 0, "invalid": 0}),
                     "cohorts": Counter({"normal": 0, "cancelled_only": 0, "diverted_only": 0,
                                         "cancelled_and_diverted": 0, "invalid_status": 0})}
    checks = {field: {"metric": metric, "checked": 0, "matched": 0, "mismatched": 0,
                      "excluded_counts": Counter(), "mismatch_examples": []}
              for field, metric in HOLDOUTS.items()}
    for source_row_number, raw in rows:
        if isinstance(source_row_number, bool) or not isinstance(source_row_number, int) or source_row_number < 1:
            raise ValueError("source_row_number must be a positive integer")
        original = normalize_bts_row(raw, airport_timezones, row_number=source_row_number)
        originals.append(original)
        raw = original.raw  # Work on the adapter's snapshot, never mutate caller data.
        if original.issues and len(issue_examples) < 10:
            issue_examples.append({
                "source_row_number": source_row_number,
                "raw_sha256": hashlib.sha256(json.dumps(
                    raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                    allow_nan=False).encode("utf-8")).hexdigest(),
                "source": original.flight.source if original.flight else "bts",
                "record_id": original.flight.record_id if original.flight else None,
                "issues": [issue.to_dict() for issue in original.issues],
                "raw_fields": {field: raw[field] for field in DIAGNOSTIC_FIELDS if field in raw},
                "flight": original.flight.to_dict() if original.flight else None,
            })
        row_codes = {issue.code for issue in original.issues}
        issues.update(row_codes)
        unresolved.update(row_codes & UNRESOLVED_CODES)
        missing_fields.update(field for field in (*CLOCK_FIELDS, *DURATION_FIELDS) if _blank(raw.get(field)))
        origin = raw.get("Origin")
        destination = raw.get("Dest")
        origin = origin.strip() if isinstance(origin, str) and origin.strip() else "<invalid>"
        destination = destination.strip() if isinstance(destination, str) and destination.strip() else "<invalid>"
        routes[f"{origin}-{destination}"] += 1
        _airport_observation(airports, raw, "Origin", origin)
        _airport_observation(airports, raw, "Dest", destination)
        day = raw.get("FlightDate")
        try:
            if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise ValueError
            dates[date.fromisoformat(day).isoformat()] += 1
        except ValueError:
            invalid_dates += 1
        cancelled, diverted = _status(raw.get("Cancelled")), _status(raw.get("Diverted"))
        status_counts["Cancelled"][cancelled] += 1
        status_counts["Diverted"][diverted] += 1
        if "invalid" in (cancelled, diverted):
            cohort, status_exclusion = "invalid_status", "invalid_status"
        elif cancelled == "1":
            cohort = "cancelled_and_diverted" if diverted == "1" else "cancelled_only"
            status_exclusion = "cancelled"
        elif diverted == "1":
            cohort, status_exclusion = "diverted_only", "diverted"
        else:
            cohort, status_exclusion = "normal", None
        status_counts["cohorts"][cohort] += 1
        probe_raw = {**raw, "ArrDelay": "", "AirTime": ""}
        probe = normalize_bts_row(probe_raw, airport_timezones, row_number=source_row_number)
        probe_error = _probe_error_reason(probe)
        metrics = flight_metrics(probe.flight) if probe.flight is not None else {}
        for source_field, check in checks.items():
            target, target_reason = _whole_minute(raw.get(source_field), signed=source_field == "ArrDelay")
            prediction = metrics.get(check["metric"])
            reason = status_exclusion
            if reason is None and target_reason is not None:
                reason = f"{target_reason}_target"
            if reason is None:
                reason = probe_error
            if reason is None and prediction is None:
                reason = "missing_derivation_fields"
            if reason is not None:
                check["excluded_counts"][reason] += 1
                continue
            check["checked"] += 1
            if Decimal(str(prediction)) == Decimal(target):
                check["matched"] += 1
            else:
                check["mismatched"] += 1
                if len(check["mismatch_examples"]) < 10:
                    check["mismatch_examples"].append({
                        "source_row_number": source_row_number, "source": probe.flight.source,
                        "record_id": probe.flight.record_id, "metric": check["metric"],
                        "predicted": prediction, "reported": target,
                    })
    report = analyze_results(originals)
    summary = summarize(report)
    accepted_source = _source_arrivals(report.accepted)
    derived_arrivals = summary["arrival_otp_15_completed"]
    parity = {key: {"source": accepted_source[key], "derived": derived_arrivals[key],
                    "matched": accepted_source[key] == derived_arrivals[key]}
              for key in ("eligible", "coverage_population", "on_time", "late", "percent", "coverage_percent")}
    count = report.input_count
    for check in checks.values():
        check["excluded_counts"] = dict(sorted(check["excluded_counts"].items()))
        check["input_rows"] = count
        check["reconciled"] = (check["checked"] + sum(check["excluded_counts"].values()) == count
                               and check["matched"] + check["mismatched"] == check["checked"])
        if not check["reconciled"]:
            raise ValueError("Hold-out accounting failed to reconcile")
    for item in airports.values():
        for key in ("airport_ids", "airport_sequence_ids"):
            item[key] = sorted(item[key], key=int)
        for key in ("observations", "missing_field_counts", "invalid_field_counts"):
            item[key] = dict(sorted(item[key].items()))
    return {
        "input_rows": count, "batch_summary": summary, "group_dispositions": report.counts,
        "source_input_kpis": {
            "all_source_rows": _source_arrivals(originals), "accepted_unique_rows": accepted_source,
            "accepted_parity": parity,
            "policy": "Original signed ArrDelay, strict delay < 15. All-source results count raw rows; accepted results use original batch dispositions. This is source-input accounting, not a held-out check.",
        },
        "holdout_checks": checks,
        "timezone_offset_transitions": timezone_offset_coverage(report, airport_timezones),
        "source_status_counts": {field: dict(values) for field, values in status_counts.items()},
        "normalizer_issue_counts": dict(sorted(issues.items())),
        "normalizer_issue_examples": issue_examples,
        "unresolved_counts": dict(sorted(unresolved.items())),
        "source_missing_fields": dict(sorted(missing_fields.items())),
        "route_counts": dict(sorted(routes.items())),
        "date_range": {"start": min(dates) if dates else None, "end": max(dates) if dates else None,
                       "valid_rows": sum(dates.values()), "invalid_rows": invalid_dates},
        "airport_ids": dict(sorted(airports.items())),
        "policy": {
            "scope": "Every caller-supplied source row; no sampling or status selection in this helper.",
            "holdouts": "ArrDelay and AirTime are withheld only in a separate probe; original rows determine batch dispositions.",
            "tolerance_minutes": 0, "midnight_policy": None, "departure_fold": None,
            "absolute_utc_validation": False,
            "duplicate_policy": "Hold-outs account for every source row; batch KPIs use original accepted unique flights.",
            "missing_policy": "Never derive dates or durations from clock order; source-clock absence is reported separately.",
            "reconstruction_checks": "Input-derived DepDelay, ActualElapsedTime and taxi KPI equalities are not claimed as independent hold-outs.",
            "issue_count_unit": "Source rows containing a code, before batch duplicate/conflict findings.",
            "exclusion_priority": "invalid/cancelled/diverted status, missing/invalid target, probe error, missing prediction.",
        },
    }
