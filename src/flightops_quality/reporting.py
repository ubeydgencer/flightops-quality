"""JSON-ready audit documents and a small escaped HTML view."""
from __future__ import annotations

import hashlib
import json
from html import escape
from typing import Any, Mapping, Optional

from . import __version__
from .analytics import summarize
from .models import BatchReport
from .rules import flight_metrics

RULESET_VERSION = "0.1.0"


def audit_document(report: BatchReport, manifest: Optional[Mapping[str, Any]] = None) -> dict:
    document = report.to_dict()
    document["package_version"] = __version__
    document["ruleset_version"] = RULESET_VERSION
    document["manifest"] = dict(manifest or {})
    document["summary"] = summarize(report)
    for category in ("accepted", "quarantined", "duplicates"):
        for entry, record in zip(document[category], getattr(report, category)):
            payload = json.dumps(dict(record.raw), sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
            entry["raw_sha256"] = hashlib.sha256(payload).hexdigest()
            entry["metrics"] = flight_metrics(record.flight) if record.accepted else None
    return document


def render_html(document: Mapping[str, Any]) -> str:
    """Escape all source-derived text, including IDs, raw data, and findings."""
    rows = []
    for category in ("accepted", "quarantined", "duplicates"):
        for entry in document[category]:
            flight = entry["flight"] or {}
            identity = f'{flight.get("source", "?")} / {flight.get("record_id", "?")}'
            findings = "\n".join(
                f'{i["severity"]}: {i["code"]} ({", ".join(i["fields"])}): {i["message"]}'
                for i in entry["issues"]
            ) or "No findings"
            raw = json.dumps(entry["raw"], ensure_ascii=False, sort_keys=True)
            rows.append(
                f'<tr><td>{escape(category)}</td><td>{entry["row_number"]}</td>'
                f'<td>{escape(identity)}</td><td><pre>{escape(findings)}</pre>'
                f'<details><summary>Raw record</summary><pre>{escape(raw)}</pre></details></td></tr>'
            )
    summary = escape(json.dumps(document["summary"], indent=2, ensure_ascii=False))
    manifest = escape(json.dumps(document["manifest"], indent=2, ensure_ascii=False))
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>FlightOps Quality audit</title><style>'
        'body{font:16px system-ui;margin:2rem auto;max-width:1200px;padding:0 1rem;color:#192434}'
        'table{border-collapse:collapse;width:100%}td,th{border:1px solid #c8d1db;padding:.6rem;text-align:left;vertical-align:top}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}'
        '</style><h1>FlightOps Quality audit</h1>'
        '<p>Accepted records may have warnings. OTP uses only eligible accepted unique flights.</p>'
        f'<h2>Summary</h2><pre>{summary}</pre><h2>Input manifest</h2><pre>{manifest}</pre>'
        '<h2>Record audit</h2><table><thead><tr><th>Disposition</th><th>Row</th>'
        '<th>Identity</th><th>Findings</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></html>\n'
    )
