"""Read-only finding counts from a closed warehouse produced by etl_sqlite.py.

Count every recorded occurrence while distinguishing affected audit records.
This optional SQL example requires SQLite json_each and json_extract support;
it does not revalidate source data or modify the warehouse.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def analyze(database: Path) -> dict:
    try:
        database = database.resolve(strict=True)
    except RuntimeError as exc:
        raise ValueError("Database path cannot be resolved") from exc
    if not database.is_file():
        raise ValueError("Database input must be a regular file")
    query = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    # as_uri() encodes filename '?' and '#' instead of treating them as options.
    # No immutable flag: a read transaction retains SQLite's locking/snapshot rules.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        try:
            probe = con.execute("SELECT json_extract(value, '$.code') FROM json_each(?)",
                                ('[{"code":"probe"}]',)).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError("Findings report requires working SQLite JSON functions "
                             f"json_each and json_extract: {exc}") from exc
        if len(probe) != 1 or probe[0][0] != "probe":
            raise ValueError("Findings report requires working SQLite JSON functions")
        con.execute("BEGIN")  # All measurements observe the same read snapshot.
        findings = [dict(row) for row in con.execute(query)]
        raw_records = con.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0]
        totals = con.execute("""
            SELECT COUNT(*) AS occurrences,
                   COUNT(DISTINCT r.audit_record_id) AS affected_records
            FROM raw_records AS r
            CROSS JOIN json_each(r.issues_json) AS j
        """).fetchone()
        return {
            "raw_records": raw_records,
            "records_with_findings": totals["affected_records"],
            "records_without_findings": raw_records - totals["affected_records"],
            "finding_occurrences": totals["occurrences"],
            "findings": findings,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    try:
        result = analyze(args.database)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"warehouse_findings: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
