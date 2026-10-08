"""Load accepted flights and every raw record into an inspectable SQLite warehouse.

Input is an audit.json created by the CLI. This example uses synthetic data in the
quickstart, but can consume either adapter's audit. No external services needed.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def load(audit_path: Path, database_path: Path) -> dict:
    if database_path.exists():
        raise ValueError("Choose a new database path to preserve the existing warehouse")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    con = sqlite3.connect(database_path)
    try:
        with con:
            con.executescript("""
                CREATE TABLE manifest (document TEXT NOT NULL);
                CREATE TABLE raw_records (
                  row_number INTEGER PRIMARY KEY, disposition TEXT NOT NULL,
                  raw_sha256 TEXT NOT NULL, raw_json TEXT NOT NULL, issues_json TEXT NOT NULL
                );
                CREATE TABLE flights (
                  source TEXT NOT NULL, record_id TEXT NOT NULL, origin TEXT NOT NULL,
                  destination TEXT NOT NULL, cancelled INTEGER NOT NULL,
                  diverted INTEGER NOT NULL, arrival_delay_minutes REAL,
                  departure_delay_minutes REAL, block_minutes REAL,
                  sobt TEXT, sibt TEXT, aobt TEXT, aibt TEXT,
                  PRIMARY KEY (source, record_id)
                );
            """)
            con.execute("INSERT INTO manifest VALUES (?)", (json.dumps(audit["manifest"]),))
            for category in ("accepted", "quarantined", "duplicates"):
                for record in audit[category]:
                    con.execute("INSERT INTO raw_records VALUES (?, ?, ?, ?, ?)", (
                        record["row_number"], category, record["raw_sha256"],
                        json.dumps(record["raw"], ensure_ascii=False),
                        json.dumps(record["issues"], ensure_ascii=False),
                    ))
                    if category != "accepted":
                        continue
                    flight, metrics = record["flight"], record["metrics"]
                    con.execute("INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                        flight["source"], flight["record_id"], flight["origin"], flight["destination"],
                        int(flight["cancelled"]), int(flight["diverted"]),
                        metrics["arrival_delay_minutes"], metrics["departure_delay_minutes"],
                        metrics["block_minutes"], flight["sobt"], flight["sibt"],
                        flight["aobt"], flight["aibt"],
                    ))
        con.row_factory = sqlite3.Row
        query = Path(__file__).with_name("route_metrics.sql").read_text(encoding="utf-8")
        return {"routes": [dict(row) for row in con.execute(query)],
                "raw_records": con.execute("SELECT count(*) FROM raw_records").fetchone()[0]}
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    print(json.dumps(load(args.audit, args.database), indent=2))
