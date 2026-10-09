"""JSON-ready audit documents and a small escaped HTML view."""
from __future__ import annotations

import hashlib
import json
from html import escape
from typing import Any, Mapping, Optional

from . import __version__
from ._raw import snapshot_raw
from .analytics import summarize
from .gates import QualityPolicy, evaluate_quality
from .models import BatchReport
from .rules import flight_metrics

RULESET_VERSION = "0.1.1"


def audit_document(report: BatchReport, manifest: Optional[Mapping[str, Any]] = None,
                   *, quality_policy: Optional[QualityPolicy] = None) -> dict:
    document = report.to_dict()
    document["package_version"] = __version__
    document["ruleset_version"] = RULESET_VERSION
    document["manifest"] = dict(manifest or {})
    document["summary"] = summarize(report)
    document["quality_gate"] = evaluate_quality(report, quality_policy)
    for category in ("accepted", "quarantined", "duplicates"):
        for entry, record in zip(document[category], getattr(report, category)):
            entry["raw"] = snapshot_raw(record.raw)
            payload = json.dumps(entry["raw"], sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
            entry["raw_sha256"] = hashlib.sha256(payload).hexdigest()
            entry["metrics"] = flight_metrics(record.flight) if record.accepted else None
    return document


def _quality_gate_html(gate: Mapping[str, Any]) -> str:
    status = str(gate.get("status", "not_configured"))
    color = {"passed": "#146c43", "failed": "#a4262c"}.get(status, "#465465")
    heading = (f'<h2>Batch quality gate</h2><p style="color:{color}">'
               f'<strong>{escape(status.replace("_", " "))}</strong></p>')
    checks = gate.get("checks", [])
    if not checks:
        return heading + '<p>No batch quality thresholds configured.</p>'
    rows = []
    for check in checks:
        observed = "Unavailable" if check["observed"] is None else str(check["observed"])
        threshold = f'{check["operator"]} {check["threshold"]}'
        cells = (check["metric"], observed, threshold,
                 "Pass" if check["passed"] else "Fail", check["reason"])
        rows.append('<tr>' + ''.join(f'<td>{escape(str(c))}</td>' for c in cells) + '</tr>')
    return (heading + '<table><thead><tr><th>Metric</th><th>Observed</th>'
            '<th>Threshold</th><th>Result</th><th>Reason</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table>')


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
                f'<tr><td>{escape(category)}</td><td>{escape(str(entry["row_number"]))}</td>'
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
        + _quality_gate_html(document.get("quality_gate", {})) +
        f'<h2>Summary</h2><pre>{summary}</pre><h2>Input manifest</h2><pre>{manifest}</pre>'
        '<h2>Record audit</h2><table><thead><tr><th>Disposition</th><th>Row</th>'
        '<th>Identity</th><th>Findings</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></html>\n'
    )
