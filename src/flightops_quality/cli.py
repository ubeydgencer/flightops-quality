"""Bounded batch CSV audit. Fail visibly when the input cannot be parsed."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
from zoneinfo import TZPATH

from . import __version__
from .adapters.bts import normalize_bts_row
from .adapters.canonical import normalize_record
from .batch import analyze_results
from .reporting import audit_document, render_html

DEFAULT_INPUT_MB = 50
DEFAULT_MAX_RECORDS = 100_000
DEFAULT_MAX_CELLS = 2_000_000
MAX_COLUMNS = 256
MAX_TIMEZONE_MAP_BYTES = 1_048_576


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"{path.name} exceeds the configured input size limit")
    return payload


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON mapping key: {key}")
        result[key] = value
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit flight CSV records without silently discarding rows")
    parser.add_argument("input", type=Path, help="UTF-8 CSV input")
    parser.add_argument("--format", choices=("canonical", "bts"), default="canonical")
    parser.add_argument("--timezones", type=Path, help="BTS airport code to IANA zone JSON mapping")
    parser.add_argument("--midnight-policy", choices=("start", "end"),
                        help="BTS scheduled 2400: explicit start/end of FlightDate (verify for the source)")
    parser.add_argument("--output", type=Path, required=True, help="New output directory (must not exist)")
    parser.add_argument("--max-input-mb", type=int, default=DEFAULT_INPUT_MB,
                        help="Maximum CSV bytes in MiB (default: 50); raise deliberately for trusted batches")
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS,
                        help="Maximum CSV records (default: 100000)")
    parser.add_argument("--max-cells", type=int, default=DEFAULT_MAX_CELLS,
                        help="Maximum records times columns (default: 2000000)")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit 1 when any row is quarantined")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.max_input_mb <= 0 or args.max_records <= 0 or args.max_cells <= 0:
            raise ValueError("Input size and record limits must be positive integers")
        if args.output.exists():
            raise ValueError("Output directory already exists; choose a new path to preserve prior audits")
        if args.format == "bts" and not args.timezones:
            raise ValueError("BTS input requires --timezones with a caller-supplied IANA timezone mapping")
        timezone_bytes = _read_bounded(args.timezones, MAX_TIMEZONE_MAP_BYTES) if args.timezones else None
        timezones = json.loads(timezone_bytes, object_pairs_hook=_unique_json_object) if timezone_bytes is not None else {}
        if not isinstance(timezones, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in timezones.items()
        ):
            raise ValueError("Timezone mapping must be a JSON object of airport-code: IANA-zone strings")
        payload = _read_bounded(args.input, args.max_input_mb * 1_048_576)
        # Hash and parse the same bytes so a concurrent source-file edit cannot
        # give the audit a manifest belonging to a different input.
        with io.StringIO(payload.decode("utf-8-sig"), newline="") as handle:
            reader = csv.reader(handle, strict=True)
            headers = next(reader, None)
            if not headers or len(set(headers)) != len(headers):
                raise ValueError("CSV needs a nonempty header with unique column names")
            if len(headers) > MAX_COLUMNS:
                raise ValueError("CSV exceeds the 256-column limit")
            results = []
            previous_line = reader.line_num
            for values in reader:
                number = previous_line + 1
                previous_line = reader.line_num
                if not values:
                    continue
                if len(results) >= args.max_records:
                    raise ValueError("CSV exceeds the configured record limit")
                if (len(results) + 1) * len(headers) > args.max_cells:
                    raise ValueError("CSV exceeds the configured cell limit")
                if len(values) != len(headers):
                    raise ValueError(f"CSV row {number} does not match header width")
                row = dict(zip(headers, values))
                if args.format == "bts":
                    results.append(normalize_bts_row(row, timezones, row_number=number,
                                                     midnight_policy=args.midnight_policy))
                else:
                    results.append(normalize_record(row, row_number=number))
        report = analyze_results(results)
        try:
            timezone_version = importlib.metadata.version("tzdata")
        except importlib.metadata.PackageNotFoundError:
            timezone_version = None
        manifest = {
            "input_name": args.input.name, "input_sha256": hashlib.sha256(payload).hexdigest(),
            "format": args.format,
            "bts_midnight_policy": args.midnight_policy if args.format == "bts" else None,
            "timezone_mapping_sha256": hashlib.sha256(timezone_bytes).hexdigest() if timezone_bytes else None,
            "timezone_database": {"tzdata_package_version": timezone_version,
                                  "system_search_paths": [str(p) for p in TZPATH],
                                  "note": "ZoneInfo searches system paths before the tzdata fallback; pin the environment for reproducibility."},
        }
        document = audit_document(report, manifest)
        args.output.mkdir(parents=True, mode=0o700)
        (args.output / "audit.json").write_text(json.dumps(document, indent=2, ensure_ascii=False,
                                                         allow_nan=False) + "\n", encoding="utf-8")
        (args.output / "audit.html").write_text(render_html(document), encoding="utf-8")
        for category in ("accepted", "quarantined", "duplicates"):
            with (args.output / f"{category}.jsonl").open("w", encoding="utf-8") as handle:
                for entry in document[category]:
                    handle.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
        print(json.dumps(document["summary"], indent=2))
        return int(args.fail_on_error and bool(report.quarantined))
    except (OSError, ValueError, csv.Error, RecursionError) as exc:
        parser.exit(2, f"flightops-quality: {exc}\n")
