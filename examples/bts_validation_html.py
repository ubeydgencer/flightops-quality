"""Render existing BTS benchmark evidence as a static offline HTML document.

This is a view of recorded evidence, not a new normalization or source validation.
Source text is escaped; the page contains no scripts, remote assets or URL links.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import tempfile
from html import escape
from pathlib import Path

from flightops_quality._raw import snapshot_raw
from flightops_quality.cli import _read_bounded, _unique_json_object

MAX_EVIDENCE_BYTES = 2 * 1_048_576
CSS = """
:root{color-scheme:dark;--bg:#0a1420;--panel:#112337;--line:#29445d;--text:#edf5fc;--muted:#b3c6d7;--accent:#79e5c7}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 system-ui,-apple-system,sans-serif}
main{max-width:1180px;margin:auto;padding:40px 24px 64px}header{border-bottom:1px solid var(--line);padding-bottom:24px}
.eyebrow{color:var(--accent);font-size:.8rem;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(2rem,5vw,3.3rem);line-height:1.15;margin:12px 0}
h2{font-size:1.55rem;margin:0 0 12px}h3{font-size:1.1rem}p{margin:12px 0}small,.muted{color:var(--muted)}
nav{display:flex;gap:18px;flex-wrap:wrap;margin:22px 0 0}a{color:var(--accent);text-underline-offset:4px}a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:4px}
section{margin:36px 0;scroll-margin-top:20px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.card{border:1px solid var(--line);background:var(--panel);padding:20px;border-radius:14px}.card strong{display:block;font-size:2rem;line-height:1.3;margin:8px 0}
.notice{border-left:3px solid var(--accent);padding:12px 18px;background:var(--panel);border-radius:0 10px 10px 0}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:.93rem}
th,td{text-align:left;padding:12px 15px;border-bottom:1px solid var(--line);vertical-align:top}th{background:var(--panel);color:var(--accent);font-weight:600}tr:last-child td{border-bottom:0}
code,pre{font: .85rem/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}pre{white-space:pre-wrap;background:var(--bg);padding:14px;border:1px solid var(--line);border-radius:8px;max-height:30rem;overflow:auto}
details{background:var(--panel);border:1px solid var(--line);padding:14px 18px;border-radius:12px;margin:14px 0}summary{cursor:pointer;font-weight:600}.pill{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:3px 11px;color:var(--accent);font-size:.85rem}
footer{border-top:1px solid var(--line);padding-top:22px;color:var(--muted)}.hash{overflow-wrap:anywhere}
@media(max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:480px){main{padding:24px 14px}.cards{grid-template-columns:1fr}th,td{padding:10px}nav{gap:12px}}
"""


def _text(value):
    if value is None:
        return "Unavailable"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    elif isinstance(value, int) and not isinstance(value, bool):
        value = f"{value:,}"
    return escape(str(value), quote=True)


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _count(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _counter(value, label):
    value = _mapping(value, label)
    for key, number in value.items():
        _count(number, f"{label}.{key}")
    return value


def _percent(value):
    return "Unavailable" if value is None else f"{value:.4f}%"


def _arrival_metrics(value, label):
    value = _mapping(value, label)
    counts = {key: _count(value.get(key), f"{label}.{key}")
              for key in ("eligible", "coverage_population", "on_time", "late")}
    if counts["eligible"] > counts["coverage_population"] or counts["on_time"] + counts["late"] != counts["eligible"]:
        raise ValueError(f"{label} populations do not reconcile")
    for key, numerator, denominator in (
        ("percent", counts["on_time"], counts["eligible"]),
        ("coverage_percent", counts["eligible"], counts["coverage_population"]),
    ):
        recorded = value.get(key)
        expected = 100 * numerator / denominator if denominator else None
        if expected is None:
            if recorded is not None:
                raise ValueError(f"{label}.{key} must be null for an empty denominator")
        elif (isinstance(recorded, bool) or not isinstance(recorded, (int, float))
              or not 0 <= recorded <= 100
              or not math.isclose(recorded, expected, rel_tol=1e-12, abs_tol=1e-12)):
            raise ValueError(f"{label}.{key} disagrees with its recorded population")
    return value


def _table(headers, rows, *, code_values=False):
    head = "".join(f"<th scope=\"col\">{_text(value)}</th>" for value in headers)
    body = ""
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            content = _text(value)
            if code_values and index == 1:
                content = f"<code>{content}</code>"
            cells.append(f"<td>{content}</td>")
        body += "<tr>" + "".join(cells) + "</tr>"
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render_validation_html(document, *, input_sha256=None):
    """Escape recorded evidence and reject contradictory count/percentage fields."""
    if not isinstance(document, dict):
        raise ValueError("Benchmark evidence must be an object")
    document = snapshot_raw(document)
    if document.get("schema_version") != "1":
        raise ValueError("Unsupported benchmark evidence schema")
    source, environment, cohort, validation = (
        _mapping(document.get(key), key) for key in ("source", "environment", "cohort", "validation")
    )
    count = _count(validation.get("input_rows"), "validation.input_rows")
    scanned = _count(source.get("source_rows_scanned"), "source.source_rows_scanned")
    if scanned < count:
        raise ValueError("Scanned source rows cannot be fewer than selected rows")
    summary = _mapping(validation.get("batch_summary"), "validation.batch_summary")
    dispositions = _counter(validation.get("group_dispositions"), "validation.group_dispositions")
    for key in ("input", "accepted", "quarantined", "duplicates"):
        _count(dispositions.get(key), f"group_dispositions.{key}")
    if dispositions["input"] != count or sum(dispositions[key] for key in ("accepted", "quarantined", "duplicates")) != count:
        raise ValueError("Batch dispositions do not reconcile")
    if _counter(summary.get("counts"), "batch_summary.counts") != dispositions:
        raise ValueError("Batch summary and dispositions disagree")
    routes = _counter(validation.get("route_counts"), "validation.route_counts")
    if sum(routes.values()) != count:
        raise ValueError("Route counts do not reconcile with selected rows")
    checks = _mapping(validation.get("holdout_checks"), "validation.holdout_checks")
    if set(checks) != {"ArrDelay", "AirTime"}:
        raise ValueError("Schema 1 requires both ArrDelay and AirTime hold-out checks")
    check_rows, exclusion_rows, mismatch_sections = [], [], []
    for field, check in checks.items():
        check = _mapping(check, f"holdout_checks.{field}")
        checked, matched, mismatched, total = (
            _count(check.get(key), f"holdout_checks.{field}.{key}")
            for key in ("checked", "matched", "mismatched", "input_rows")
        )
        excluded = _counter(check.get("excluded_counts"), f"holdout_checks.{field}.excluded_counts")
        if total != count or checked + sum(excluded.values()) != count or matched + mismatched != checked or check.get("reconciled") is not True:
            raise ValueError(f"{field} hold-out populations do not reconcile")
        check_rows.append((field, check.get("metric"), checked, matched, mismatched,
                           "No comparable observations" if not checked else f"{matched:,} / {checked:,} matched"))
        exclusion_rows.extend((field, reason, number) for reason, number in excluded.items())
        examples = check.get("mismatch_examples", [])
        if not isinstance(examples, list) or len(examples) > 10:
            raise ValueError("Hold-out examples must be a list of at most ten rows")
        if examples:
            mismatch_sections.append(f'<h3>{_text(field)} mismatch examples</h3><pre>{_text(json.dumps(examples, indent=2, ensure_ascii=False))}</pre>')
    kpis = _mapping(validation.get("source_input_kpis"), "validation.source_input_kpis")
    raw = _arrival_metrics(kpis.get("all_source_rows"), "source_input_kpis.all_source_rows")
    accepted = _arrival_metrics(kpis.get("accepted_unique_rows"), "source_input_kpis.accepted_unique_rows")
    derived = _arrival_metrics(summary.get("arrival_otp_15_completed"), "batch_summary.arrival_otp_15_completed")
    if (_count(raw.get("input_rows"), "all_source_rows.input_rows") != count
            or _count(accepted.get("input_rows"), "accepted_unique_rows.input_rows") != dispositions["accepted"]):
        raise ValueError("Source-input KPI row counts disagree with batch dispositions")
    if raw["coverage_population"] > count or accepted["coverage_population"] > dispositions["accepted"] or derived["coverage_population"] > dispositions["accepted"]:
        raise ValueError("Arrival coverage population exceeds its source population")
    kpi_rows = []
    for label, item in (("Source labels · all selected rows", raw),
                        ("Source labels · accepted unique", accepted),
                        ("Derived metrics · accepted unique", derived)):
        kpi_rows.append((label, item["eligible"], item["on_time"], item["late"],
                         _percent(item["percent"]),
                         f'{item["eligible"]:,} / {item["coverage_population"]:,} · {_percent(item["coverage_percent"])}'))
    issue_counts = _counter(validation.get("normalizer_issue_counts"), "validation.normalizer_issue_counts")
    finding_counts = _counter(summary.get("issue_counts"), "batch_summary.issue_counts")
    issue_rows = [(code, issue_counts.get(code, 0), finding_counts.get(code, 0))
                  for code in sorted(set(issue_counts) | set(finding_counts))]
    diagnostic_sections = []
    examples = validation.get("normalizer_issue_examples", [])
    if not isinstance(examples, list) or len(examples) > 10:
        raise ValueError("Normalizer examples must be a list of at most ten rows")
    for example in examples:
        example = _mapping(example, "normalizer_issue_examples entry")
        fields = _mapping(example.get("raw_fields"), "normalizer_issue_examples.raw_fields")
        issues = example.get("issues")
        if not isinstance(issues, list):
            raise ValueError("Normalizer example issues must be a list")
        rows = []
        for issue in issues:
            issue = _mapping(issue, "diagnostic issue")
            rows.append((issue.get("code"), issue.get("severity"), issue.get("fields"), issue.get("message")))
        diagnostic_sections.append(
            f'<details><summary>Source CSV line {_text(example.get("source_row_number"))} · {_text(fields.get("Origin"))} → {_text(fields.get("Dest"))}</summary>'
            f'<p class="hash">Original raw-row SHA-256: <code>{_text(example.get("raw_sha256"))}</code></p>'
            + _table(("Code", "Severity", "Fields", "Finding"), rows)
            + '<h3>Original source fields</h3>' + _table(("Field", "Recorded value"), fields.items())
            + f'<h3>Recorded normalized flight · UTC timestamps</h3><pre>{_text(json.dumps(example.get("flight"), indent=2, ensure_ascii=False))}</pre></details>'
        )
    missing = _counter(validation.get("source_missing_fields"), "validation.source_missing_fields")
    statuses = _mapping(validation.get("source_status_counts"), "validation.source_status_counts")
    status_cohorts = _counter(statuses.get("cohorts"), "validation.source_status_counts.cohorts")
    if sum(status_cohorts.values()) != count:
        raise ValueError("Source status cohorts do not reconcile")
    zones = _mapping(cohort.get("airport_timezones"), "cohort.airport_timezones")
    period = source.get("period")
    cards = "".join(f'<div class="card"><span class="muted">{label}</span><strong>{_text(number)}</strong><small>{note}</small></div>'
                    for label, number, note in (
                        ("Scanned source rows", scanned, "Recorded source CSV scan"),
                        ("Selected route rows", count, "All source statuses retained"),
                        ("Accepted unique", dispositions["accepted"], "Original batch disposition"),
                        ("Quarantined", dispositions["quarantined"], "Review the recorded findings")))
    provenance_rows = [("Period", period), ("Source date range", source.get("source_date_range")),
                       ("Source URL label · no request", source.get("source_url_label")),
                       ("Archive name", source.get("archive_name")), ("Archive bytes", source.get("archive_bytes")),
                       ("Archive SHA-256", source.get("archive_sha256")), ("CSV member", source.get("csv_member")),
                       ("CSV bytes", source.get("csv_bytes")), ("CSV SHA-256", source.get("csv_sha256")),
                       ("Timezone mapping SHA-256", cohort.get("timezone_mapping_sha256")),
                       ("Extracted cohort artifact", document.get("cohort_artifact"))]
    if input_sha256 is not None:
        provenance_rows.append(("Rendered validation JSON SHA-256", input_sha256))
    policy = _mapping(validation.get("policy"), "validation.policy")
    style_hash = base64.b64encode(hashlib.sha256(CSS.encode("utf-8")).digest()).decode("ascii")
    csp = f"default-src 'none'; style-src 'sha256-{style_hash}'; base-uri 'none'; form-action 'none'"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}">'
        f'<title>BTS route-cohort evidence · {_text(period)} | FlightOps Quality</title><style>{CSS}</style></head><body><main>'
        '<header><div class="eyebrow">FlightOps Quality · civil aviation data engineering</div>'
        f'<h1>BTS route-cohort evidence</h1><p><span class="pill">{_text(period)}</span> · {_text(" · ".join(zones))}</p>'
        '<p class="muted">An offline view of recorded source consistency. This page does not rerun normalization or establish independent ground truth.</p>'
        '<nav aria-label="Report sections"><a href="#accounting">Accounting</a><a href="#checks">Held-out checks</a><a href="#metrics">Metrics</a><a href="#findings">Findings</a><a href="#provenance">Provenance</a></nav></header>'
        f'<section id="accounting"><h2>Source and selected cohort</h2><div class="cards">{cards}</div>'
        f'<p class="notice">Selection predicate: {_text(cohort.get("predicate"))}</p>'
        + _table(("Disposition", "Source rows"), dispositions.items())
        + '<h3>Selected routes · source-row counts</h3>' + _table(("Route", "Rows"), routes.items())
        + '<h3>Source status cohorts · mutually exclusive</h3>' + _table(("Cohort", "Rows"), status_cohorts.items())
        + '</section><section id="checks"><h2>Held-out source-field checks</h2>'
        '<p>ArrDelay and AirTime are withheld only in a separate probe. Original rows determine the batch dispositions. A match refers to a comparable observation, not every selected flight.</p>'
        + _table(("Source field", "Derived metric", "Compared", "Matched", "Mismatched", "Comparison population"), check_rows)
        + '<h3>Comparison exclusions · source rows</h3>'
        + (_table(("Source field", "Exclusion reason", "Rows"), exclusion_rows) if exclusion_rows else '<p>No excluded observations in these recorded checks.</p>')
        + ''.join(mismatch_sections)
        + '</section><section id="metrics"><h2>Arrival OTP and observation coverage</h2>'
        '<p>On time means arrival delay &lt; 15 minutes; exactly 15 is late. OTP uses eligible flights. Coverage uses all normal flights in the stated population. Empty denominators are unavailable.</p>'
        + _table(("Population", "Eligible", "On time", "Late", "OTP", "Arrival coverage · eligible / population"), kpi_rows)
        + '<p class="muted">Source-input accounting and held-out reconstruction are separate evidence. Both depend on fields reported by the same provider; neither independently validates absolute UTC dates.</p>'
        + '</section><section id="findings"><h2>Recorded quality findings</h2>'
        + (_table(("Code", "Source rows containing normalizer code", "Batch finding occurrences"), issue_rows) if issue_rows else '<p>No recorded findings.</p>')
        + '<p class="muted">Each normalizer code counts affected source rows once. Batch occurrences count individual findings, including group findings. Diagnostic examples show at most ten source rows and are not totals.</p>'
        + ''.join(diagnostic_sections)
        + '<h3>Missing fields · all selected source rows</h3><p class="muted">These counts include cancellation and diversion. They are not missing-KPI counts for accepted normal flights.</p>'
        + (_table(("Source field", "Rows missing the field"), missing.items()) if missing else '<p>No missing fields recorded.</p>')
        + '</section><section id="provenance"><h2>Artifact identity and recorded environment</h2>'
        + _table(("Recorded input", "Value"), provenance_rows, code_values=True)
        + '<p class="muted">Hashes identify exact bytes; they are not BTS signatures. A source URL is a label and is displayed as text.</p>'
        + '<h3>Recorded airport timezone map</h3>' + _table(("Airport", "IANA zone"), zones.items())
        + '<h3>Environment of the evidence producer</h3>' + _table(("Field", "Recorded value"), environment.items())
        + '<h3>Recorded reconstruction policy</h3>' + _table(("Policy", "Recorded value"), policy.items())
        + '</section><footer><p>Scope: one dated route cohort. A full source scan is not full-month/all-airport flight validation. Timezone and DST-transition coverage require dated source evidence. Scheduled midnight, DST folds, other periods and production feeds need separate evidence.</p>'
        '<p>This static view has no scripts or remote assets. Keep it with the original validation JSON and source artifacts. FlightOps Quality is an independent alpha project.</p></footer></main></body></html>'
    )


def write_html(html, destination):
    """Publish a private complete file through an exclusive same-directory link."""
    if not destination.name or destination.name in {".", ".."}:
        raise ValueError("Choose a new named HTML file")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = destination.parent.resolve(strict=True) / destination.name
    if os.path.lexists(destination):
        raise FileExistsError("HTML output already exists")
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}-", suffix=".staging", dir=destination.parent)
    staging = Path(name)
    try:
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            handle.write(html)
        os.link(staging, destination, follow_symlinks=False)
    finally:
        staging.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Recorded validation JSON (at most 2 MiB)")
    parser.add_argument("--output", type=Path, required=True, help="New HTML file; existing paths are preserved")
    args = parser.parse_args(argv)
    try:
        if os.path.lexists(args.output):
            raise FileExistsError("HTML output already exists")
        payload = _read_bounded(args.input, MAX_EVIDENCE_BYTES)
        document = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_json_object)
        html = render_validation_html(document, input_sha256=hashlib.sha256(payload).hexdigest())
        write_html(html, args.output)
        print(str(args.output))
        return 0
    except (OSError, ValueError, KeyError, RecursionError) as exc:
        parser.exit(2, f"bts_validation_html: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
