"""Offline, bounded validation of a dated BTS archive and mapped route cohort.

Run from a checkout with flightops-quality installed. No ZIP member is extracted;
all source rows are scanned before a complete, exclusive output is published.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import re
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import TZPATH, ZoneInfo

from bts_validation import validate_rows
from flightops_quality import __version__
from flightops_quality.cli import (
    _private_text_file, _publish_directory, _read_bounded, _unique_json_object,
)
from flightops_quality.reporting import RULESET_VERSION

MAX_ARCHIVE_BYTES = 64 * 1_048_576
MAX_CSV_BYTES = 512 * 1_048_576
MAX_SOURCE_ROWS = 1_000_000
MAX_COHORT_ROWS = 20_000
MAX_COHORT_CELLS = 2_000_000
MAX_COHORT_BYTES = 64 * 1_048_576
MAX_COLUMNS = 256
REQUIRED_FIELDS = {
    "FlightDate", "Origin", "Dest", "OriginAirportID", "OriginAirportSeqID",
    "DestAirportID", "DestAirportSeqID", "Reporting_Airline",
    "Flight_Number_Reporting_Airline", "CRSDepTime", "CRSArrTime", "CRSElapsedTime",
    "DepTime", "ArrTime", "DepDelay", "ArrDelay", "ActualElapsedTime", "TaxiOut",
    "TaxiIn", "WheelsOff", "WheelsOn", "AirTime", "Cancelled", "Diverted",
}
SOURCE_LINE_FIELD = "_source_line_number"


class _DigestReader(io.RawIOBase):
    def __init__(self, source, limit):
        super().__init__()
        self.source, self.limit = source, limit
        self.byte_count = 0
        self.digest = hashlib.sha256()

    def readable(self):
        return True

    def readinto(self, buffer):
        chunk = self.source.read(min(len(buffer), self.limit - self.byte_count + 1))
        if self.byte_count + len(chunk) > self.limit:
            raise ValueError("Decompressed CSV exceeds the byte limit")
        self.byte_count += len(chunk)
        self.digest.update(chunk)
        buffer[:len(chunk)] = chunk
        return len(chunk)


def _period(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ValueError("Period must be YYYY-MM")
    date.fromisoformat(value + "-01")
    return value


def load_timezones(path):
    payload = _read_bounded(path, 1_048_576)
    zones = json.loads(payload, object_pairs_hook=_unique_json_object)
    if not isinstance(zones, dict) or not zones or len(zones) > 256:
        raise ValueError("Timezone map must contain 1–256 airport entries")
    for code, name in zones.items():
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{3}", code):
            raise ValueError("Timezone map keys must be three uppercase airport letters")
        if not isinstance(name, str) or len(name) > 128:
            raise ValueError("Timezone map values must be IANA zone names")
        ZoneInfo(name)
    return zones, hashlib.sha256(payload).hexdigest()


def read_cohort(archive, expected_sha256, period, airport_timezones):
    """Snapshot compressed bytes; fully scan and hash the CSV, retaining a cohort."""
    _period(period)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("Expected SHA-256 must contain 64 hexadecimal characters")
    payload = _read_bounded(archive, MAX_ARCHIVE_BYTES)
    archive_hash = hashlib.sha256(payload).hexdigest()
    if archive_hash != expected_sha256.lower():
        raise ValueError("Archive SHA-256 does not match the expected source artifact")
    rows, dates = [], set()
    source_count = 0
    cohort_bytes = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        members = bundle.infolist()
        csv_members = [member for member in members if member.filename.lower().endswith(".csv")]
        if len(members) > 16 or len(csv_members) != 1 or csv_members[0].is_dir():
            raise ValueError("Archive must contain exactly one CSV and at most 16 members")
        member = csv_members[0]
        if member.flag_bits & 1 or member.file_size > MAX_CSV_BYTES:
            raise ValueError("CSV is encrypted or exceeds the decompressed byte limit")
        with bundle.open(member) as source:
            raw = _DigestReader(source, MAX_CSV_BYTES)
            with io.TextIOWrapper(io.BufferedReader(raw), encoding="utf-8-sig", newline="") as text:
                reader = csv.reader(text, strict=True)
                headers = next(reader, None)
                if (not headers or len(headers) > MAX_COLUMNS
                        or len(set(headers)) != len(headers)
                        or any(not name for name in headers[:-1])
                        or SOURCE_LINE_FIELD in headers):
                    raise ValueError("CSV requires unique headers, at most 256 columns, and no reserved field")
                if not REQUIRED_FIELDS.issubset(headers):
                    raise ValueError("CSV is missing required Reporting Carrier fields")
                previous_line = reader.line_num
                for values in reader:
                    line = previous_line + 1
                    previous_line = reader.line_num
                    source_count += 1
                    if source_count > MAX_SOURCE_ROWS:
                        raise ValueError("CSV exceeds the source record limit")
                    if len(values) != len(headers):
                        raise ValueError(f"Source CSV row {line} does not match header width")
                    row = dict(zip(headers, values))
                    if headers[-1] == "" and row[""]:
                        raise ValueError(f"Source CSV row {line} has a value in the unnamed trailing column")
                    day = row["FlightDate"]
                    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
                        raise ValueError(f"Source CSV row {line} has an invalid FlightDate")
                    date.fromisoformat(day)
                    if day[:7] != period:
                        raise ValueError(f"Source CSV row {line} is outside the requested period")
                    dates.add(day)
                    if row["Origin"] in airport_timezones and row["Dest"] in airport_timezones:
                        cohort_bytes += sum(len(value.encode("utf-8")) for value in values)
                        if (len(rows) >= MAX_COHORT_ROWS
                                or (len(rows) + 1) * len(headers) > MAX_COHORT_CELLS
                                or cohort_bytes > MAX_COHORT_BYTES):
                            raise ValueError("Selected cohort exceeds record, cell or byte limits; nothing was truncated")
                        rows.append((line, row))
            csv_hash, csv_bytes = raw.digest.hexdigest(), raw.byte_count
        if csv_bytes != member.file_size:
            raise ValueError("Decompressed size disagrees with the ZIP member manifest")
    if not rows:
        raise ValueError("No source records match the mapped airport cohort")
    manifest = {
        "archive_name": archive.name, "archive_sha256": archive_hash, "archive_bytes": len(payload),
        "csv_member": member.filename, "csv_sha256": csv_hash, "csv_bytes": csv_bytes,
        "source_rows_scanned": source_count, "columns": len(headers),
        "source_date_range": {"start": min(dates), "end": max(dates)}, "period": period,
    }
    return rows, headers, manifest


def runtime_environment():
    try:
        import tzdata
        tzdata_version, iana_version = tzdata.__version__, tzdata.IANA_VERSION
    except ImportError:
        tzdata_version = iana_version = None
    return {
        "python": platform.python_version(), "system": platform.system(),
        "package_version": __version__,
        "ruleset_version": RULESET_VERSION,
        "tzdata_package_version": tzdata_version, "tzdata_iana_version": iana_version,
        "timezone_system_search_paths": list(TZPATH),
        "timezone_note": "ZoneInfo uses system search paths first. Set PYTHONTZPATH='' and pin tzdata for replay.",
    }


def publish(document, rows, headers, destination):
    if not destination.name or destination.name in {".", ".."}:
        raise ValueError("Choose a new named output directory")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    if os.path.lexists(destination):
        raise FileExistsError("Output path already exists")
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", suffix=".staging", dir=parent))
    try:
        with _private_text_file(staging / "cohort.csv") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow([*headers, SOURCE_LINE_FIELD])
            for line, raw in rows:
                writer.writerow([*(raw[name] for name in headers), line])
        cohort_hash = hashlib.sha256((staging / "cohort.csv").read_bytes()).hexdigest()
        document = {**document, "cohort_artifact": {"name": "cohort.csv", "sha256": cohort_hash,
                    "source_line_field": SOURCE_LINE_FIELD,
                    "note": "Added source line metadata is excluded from normalization and duplicate fingerprints."}}
        with _private_text_file(staging / "validation.json") as handle:
            handle.write(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        _publish_directory(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--period", required=True, help="YYYY-MM; every source row must belong to this month")
    parser.add_argument("--timezones", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory, published after the complete scan")
    parser.add_argument("--source-url", help="Optional provenance label; this script never fetches a URL")
    args = parser.parse_args(argv)
    try:
        if os.path.lexists(args.output):
            raise FileExistsError("Output path already exists")
        if args.source_url:
            url = urlsplit(args.source_url)
            if (len(args.source_url) > 2048 or url.scheme != "https" or not url.hostname
                    or url.username or url.password or url.query or url.fragment):
                raise ValueError("Source URL label must be an HTTPS URL without credentials, query or fragment")
        zones, mapping_hash = load_timezones(args.timezones)
        rows, headers, source = read_cohort(args.archive, args.expected_sha256, args.period, zones)
        source["source_url_label"] = args.source_url
        validation = validate_rows(rows, zones)
        document = {
            "schema_version": "1", "source": source, "environment": runtime_environment(),
            "cohort": {"airport_codes": sorted(zones), "airport_timezones": zones,
                       "timezone_mapping_sha256": mapping_hash,
                       "predicate": "Origin and Dest both belong to the timezone mapping keys; all statuses retained.",
                       "truncated": False, "full_cohort_bundled": False,
                       "diagnostic_source_excerpts": bool(validation["normalizer_issue_examples"])},
            "limits": {"archive_bytes": MAX_ARCHIVE_BYTES, "csv_bytes": MAX_CSV_BYTES,
                       "source_rows": MAX_SOURCE_ROWS, "cohort_rows": MAX_COHORT_ROWS,
                       "cohort_cells": MAX_COHORT_CELLS, "cohort_value_bytes": MAX_COHORT_BYTES,
                       "columns": MAX_COLUMNS},
            "validation": validation,
        }
        publish(document, rows, headers, args.output)
        print(json.dumps({"source_rows_scanned": source["source_rows_scanned"],
                          "cohort_rows": validation["input_rows"],
                          "dispositions": validation["group_dispositions"],
                          "holdout_checks": validation["holdout_checks"]}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, csv.Error, zipfile.BadZipFile,
            NotImplementedError, RecursionError) as exc:
        parser.exit(2, f"validate_bts_month: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
