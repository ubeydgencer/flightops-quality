"""Load accepted flights and every raw record into an inspectable SQLite warehouse.

Input is an audit.json created by the CLI. This example uses synthetic data in the
quickstart, but can consume either adapter's audit. No external services needed.
Failed quality gates require an explicit manual override, retained in metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from pathlib import Path
from datetime import date

from flightops_quality._raw import snapshot_raw
from flightops_quality.analytics import summarize
from flightops_quality.gates import QualityPolicy, evaluate_quality
from flightops_quality.models import BatchReport, FlightLeg, Issue, RecordResult
from flightops_quality.rules import flight_metrics, validate_leg
from flightops_quality.time import resolve_timestamp


def _audit_issues(record: dict) -> tuple[Issue, ...]:
    """Retain recorded findings without rerunning provider normalization."""
    issues = record.get("issues")
    if not isinstance(issues, list):
        raise ValueError("Audit records require a list of findings")
    result = []
    for issue in issues:
        if (not isinstance(issue, dict) or set(issue) != {"code", "severity", "fields", "message"}
                or any(not isinstance(issue[field], str) for field in ("code", "severity", "message"))
                or not isinstance(issue["fields"], list)
                or any(not isinstance(field, str) for field in issue["fields"])):
            raise ValueError("Audit findings do not match the recorded finding contract")
        snapshot_raw(issue)  # Validate UTF-8 text before retaining it in metadata.
        result.append(Issue(issue["code"], issue["severity"], tuple(issue["fields"]), issue["message"]))
    return tuple(result)


def _audit_report(audit: dict) -> BatchReport:
    """Rehydrate the normalized v0.1/v0.2 flight contract, not provider raw rows.

    Raw BTS/canonical records are retained for lineage, not normalized again with
    a potentially different timezone database. Stored KPI values must match the
    normalized offset-aware timestamps before they can enter the warehouse.
    """
    accepted = []
    for record in audit["accepted"]:
        if not isinstance(record, dict) or not isinstance(record.get("flight"), dict):
            raise ValueError("Accepted audit records require a normalized flight")
        data = dict(record["flight"])
        for field in ("source", "record_id", "carrier", "flight_number", "origin", "destination"):
            if not isinstance(data.get(field), str) or not data[field].strip():
                raise ValueError("Normalized flight identities must be nonempty strings")
        provenance = data.get("provenance")
        if not isinstance(provenance, dict) or any(
            not isinstance(field, str) or not isinstance(inputs, list)
            or any(not isinstance(value, str) for value in inputs)
            for field, inputs in provenance.items()
        ):
            raise ValueError("Normalized provenance must map fields to lists of source field names")
        for flag in ("cancelled", "diverted"):
            if not isinstance(data.get(flag), bool):
                raise ValueError("Normalized flight status flags must be booleans")
        service_date = data.get("service_date")
        if (not isinstance(service_date, str) or len(service_date) != 10
                or service_date[4] != "-" or service_date[7] != "-"):
            raise ValueError("Normalized service_date must be YYYY-MM-DD")
        try:
            data["service_date"] = date.fromisoformat(service_date)
        except ValueError as exc:
            raise ValueError("Normalized service_date is invalid") from exc
        for field in ("sobt", "sibt", "aobt", "aibt", "atot", "aldt"):
            if field not in data:
                raise ValueError(f"Normalized flight is missing timestamp field {field}")
            if data[field] is not None and (not isinstance(data[field], str) or not data[field]):
                raise ValueError("Normalized timestamps must be offset-aware ISO strings or null")
            result = resolve_timestamp(data[field])
            if result.issues:
                raise ValueError(f"Normalized flight has an invalid or non-aware {field}")
            data[field] = result.value
        try:
            flight = FlightLeg(**data)
        except TypeError as exc:
            raise ValueError("Normalized flight does not match the audit contract") from exc
        if any(issue.severity == "error" for issue in validate_leg(flight)):
            raise ValueError("Accepted normalized flight fails chronology validation")
        issues = _audit_issues(record)
        if any(issue.severity == "error" for issue in issues):
            raise ValueError("Accepted audit records cannot contain error findings")
        metrics = record.get("metrics")
        expected = flight_metrics(flight)
        if not isinstance(metrics, dict) or set(metrics) != set(expected):
            raise ValueError("Accepted audit records require every KPI field")
        for metric, value in metrics.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or (isinstance(value, float) and not math.isfinite(value))):
                raise ValueError("Stored flight KPI values must be finite numbers or null")
            if value != expected[metric]:
                raise ValueError("Stored flight KPI values contradict normalized timestamps or status")
        accepted.append(RecordResult(flight, issues, {}))
    def findings_only(category):
        return tuple(RecordResult(None, _audit_issues(record), {}) for record in audit[category])
    return BatchReport(tuple(accepted), findings_only("quarantined"),
                       findings_only("duplicates"), audit["counts"]["input"])


def _validate_summary(audit: dict, report: BatchReport) -> None:
    expected = summarize(report)
    summary = audit.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("Audit requires a recorded summary")
    snapshot_raw(summary)  # Reject nonfinite, invalid UTF-8 or deeply nested metadata.
    # v0.1 producers did not emit the two arrival-coverage fields. Permit only
    # that known, paired omission without discarding any supplied measurements.
    otp = summary.get("arrival_otp_15_completed")
    if (audit.get("package_version") in ("0.1.0", "0.1.1") and "quality_gate" not in audit
            and isinstance(otp, dict)
            and "coverage_population" not in otp and "coverage_percent" not in otp):
        expected["arrival_otp_15_completed"].pop("coverage_population")
        expected["arrival_otp_15_completed"].pop("coverage_percent")
    if (json.dumps(summary, sort_keys=True, allow_nan=False)
            != json.dumps(expected, sort_keys=True, allow_nan=False)):
        raise ValueError("Audit summary contradicts its records, findings or normalized timestamps")


def _quality_gate_status(audit: dict, allow_failed: bool, report: BatchReport) -> tuple[str, bool]:
    if not isinstance(allow_failed, bool):
        raise ValueError("allow_failed_quality_gate must be an explicit boolean")
    if "quality_gate" not in audit:
        return "legacy", False
    gate = audit["quality_gate"]
    if (not isinstance(gate, dict) or not isinstance(gate.get("status"), str)
            or gate["status"] not in {"not_configured", "passed", "failed"}):
        raise ValueError("Audit has an unknown or malformed quality gate")
    policy = gate.get("policy")
    if not isinstance(policy, dict) or set(policy) != set(QualityPolicy().to_dict()):
        raise ValueError("Audit has an incomplete quality gate policy")
    expected = evaluate_quality(report, QualityPolicy(**policy))
    # Compare the gate to the independently reconstructed accepted cohort and
    # disposition counts. An override never permits a contradictory audit.
    # JSON comparison also distinguishes false/0 and true/1, unlike dict equality.
    if (json.dumps(gate, sort_keys=True, allow_nan=False)
            != json.dumps(expected, sort_keys=True, allow_nan=False)):
        raise ValueError("Audit quality gate contradicts its records, measurements or policy")
    status = expected["status"]
    if status == "failed" and not allow_failed:
        raise ValueError("Audit quality gate failed; use an explicit allow_failed_quality_gate=True manual override")
    return status, status == "failed" and allow_failed


def _validate_counts(audit: dict) -> None:
    counts = audit.get("counts")
    categories = ("accepted", "quarantined", "duplicates")
    if not isinstance(counts, dict) or any(not isinstance(audit.get(c), list) for c in categories):
        raise ValueError("Audit requires category lists and reconciled counts")
    expected = {category: len(audit[category]) for category in categories}
    expected["input"] = sum(expected.values())
    if counts != expected or any(isinstance(v, bool) or not isinstance(v, int) for v in counts.values()):
        raise ValueError("Audit counts do not reconcile to the records")


def _reject_constant(value):
    raise ValueError(f"Audit contains a nonfinite JSON number: {value}")


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Audit contains a duplicate JSON object key")
        result[key] = value
    return result


def _validate_raw_hashes(audit: dict) -> None:
    """Check the producer's raw snapshot digest before creating a database.

    This detects inconsistent audit contents; it is not author authentication.
    Do not normalize source rows again or infer new timestamps during loading.
    """
    for category in ("accepted", "quarantined", "duplicates"):
        for record in audit[category]:
            if not isinstance(record, dict):
                raise ValueError("Audit records must be JSON objects")
            raw = snapshot_raw(record.get("raw"))
            payload = json.dumps(raw, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
            expected = hashlib.sha256(payload).hexdigest()
            if record.get("raw_sha256") != expected:
                raise ValueError("Audit raw_sha256 does not match its raw record")


def load(audit_path: Path, database_path: Path, *, allow_failed_quality_gate: bool = False) -> dict:
    if os.path.lexists(database_path):
        raise ValueError("Choose a new database path to preserve the existing warehouse")
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"),
                           parse_constant=_reject_constant, object_pairs_hook=_unique_json_object)
    except RecursionError as exc:
        raise ValueError("Audit JSON nesting exceeds the parser limit") from exc
    if not isinstance(audit, dict):
        raise ValueError("Audit must be a JSON object")
    _validate_counts(audit)
    _validate_raw_hashes(audit)
    report = _audit_report(audit)
    _validate_summary(audit, report)
    gate_status, gate_override = _quality_gate_status(audit, allow_failed_quality_gate, report)
    query = Path(__file__).with_name("route_metrics.sql").read_text(encoding="utf-8")
    database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = database_path.parent.resolve(strict=True)
    database_path = parent / database_path.name
    with tempfile.TemporaryDirectory(prefix=f".{database_path.name}-", suffix=".staging", dir=parent) as folder:
        fd, temporary_name = tempfile.mkstemp(prefix="warehouse-", suffix=".db", dir=folder)
        os.close(fd)  # mkstemp creates the database with private 0600 permissions.
        temporary = Path(temporary_name)
        con = sqlite3.connect(temporary)
        try:
            con.execute("PRAGMA foreign_keys = ON")
            with con:
                con.executescript("""
                    CREATE TABLE manifest (document TEXT NOT NULL);
                    CREATE TABLE audit_metadata (
                      package_version TEXT, ruleset_version TEXT,
                      quality_gate_status TEXT NOT NULL, quality_gate_override INTEGER NOT NULL,
                      quality_gate_json TEXT, counts_json TEXT NOT NULL, summary_json TEXT NOT NULL
                    );
                    CREATE TABLE raw_records (
                      audit_record_id INTEGER PRIMARY KEY, row_number INTEGER NOT NULL,
                      disposition TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
                      raw_json TEXT NOT NULL, issues_json TEXT NOT NULL
                    );
                    CREATE TABLE flights (
                      audit_record_id INTEGER NOT NULL UNIQUE REFERENCES raw_records(audit_record_id),
                      source TEXT NOT NULL, record_id TEXT NOT NULL, service_date TEXT NOT NULL,
                      carrier TEXT NOT NULL, flight_number TEXT NOT NULL,
                      origin TEXT NOT NULL, destination TEXT NOT NULL, aircraft_registration TEXT,
                      cancelled INTEGER NOT NULL, diverted INTEGER NOT NULL,
                      arrival_delay_minutes REAL, departure_delay_minutes REAL, block_minutes REAL,
                      taxi_out_minutes REAL, taxi_in_minutes REAL, airborne_minutes REAL,
                      sobt TEXT, sibt TEXT, aobt TEXT, aibt TEXT, atot TEXT, aldt TEXT,
                      provenance_json TEXT NOT NULL, normalized_json TEXT NOT NULL,
                      PRIMARY KEY (source, record_id)
                    );
                """)
                con.execute("INSERT INTO manifest VALUES (?)", (json.dumps(audit["manifest"]),))
                con.execute("INSERT INTO audit_metadata VALUES (?, ?, ?, ?, ?, ?, ?)", (
                    audit.get("package_version"), audit.get("ruleset_version"), gate_status,
                    int(gate_override), json.dumps(audit["quality_gate"]) if "quality_gate" in audit else None,
                    json.dumps(audit["counts"]), json.dumps(audit["summary"]),
                ))
                audit_record_id = 0
                for category in ("accepted", "quarantined", "duplicates"):
                    for record in audit[category]:
                        audit_record_id += 1
                        row_number = record["row_number"]
                        if isinstance(row_number, bool) or not isinstance(row_number, int) or row_number < 1:
                            raise ValueError("Audit source row_number must be a positive integer")
                        con.execute("INSERT INTO raw_records VALUES (?, ?, ?, ?, ?, ?)", (
                            audit_record_id, row_number, category, record["raw_sha256"],
                            json.dumps(record["raw"], ensure_ascii=False),
                            json.dumps(record["issues"], ensure_ascii=False),
                        ))
                        if category != "accepted":
                            continue
                        flight, metrics = record["flight"], record["metrics"]
                        values = {**flight, **metrics, "audit_record_id": audit_record_id,
                                  "cancelled": int(flight["cancelled"]), "diverted": int(flight["diverted"]),
                                  "provenance_json": json.dumps(flight["provenance"], ensure_ascii=False),
                                  "normalized_json": json.dumps(flight, ensure_ascii=False)}
                        con.execute("""INSERT INTO flights VALUES (
                            :audit_record_id, :source, :record_id, :service_date, :carrier, :flight_number,
                            :origin, :destination, :aircraft_registration, :cancelled, :diverted,
                            :arrival_delay_minutes, :departure_delay_minutes, :block_minutes,
                            :taxi_out_minutes, :taxi_in_minutes, :airborne_minutes,
                            :sobt, :sibt, :aobt, :aibt, :atot, :aldt, :provenance_json, :normalized_json
                        )""", values)
            con.row_factory = sqlite3.Row
            routes = [dict(row) for row in con.execute(query)]
            raw_count = con.execute("SELECT count(*) FROM raw_records").fetchone()[0]
            if raw_count != audit["counts"]["input"]:
                raise ValueError("Warehouse raw record count does not match the audit")
            if con.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Warehouse record lineage does not reconcile")
            result = {"routes": routes, "raw_records": raw_count,
                      "quality_gate_status": gate_status, "quality_gate_override": gate_override}
        finally:
            con.close()
        # A hard link publishes the complete closed database and fails atomically
        # if any destination (including a dangling symlink) already exists.
        os.link(temporary, database_path, follow_symlinks=False)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--allow-failed-quality-gate", action="store_true",
                        help="Explicit manual override; the failed gate and override remain in warehouse metadata")
    args = parser.parse_args()
    try:
        result = load(args.audit, args.database, allow_failed_quality_gate=args.allow_failed_quality_gate)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"etl_sqlite: {exc}\n")
    print(json.dumps(result, indent=2))
