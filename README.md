# FlightOps Quality

Explainable flight operations data quality for Python ETL pipelines. Normalize
gate and runway timestamps to UTC, retain uncertain observations with findings,
and separate exact duplicates from conflicting records before calculating KPIs.

**Status: v0.1 alpha.** Python 3.9+, no mandatory runtime dependencies. This is an
independent open-source project, with no airline affiliation or certification.
All bundled flight records are **synthetic**, including the Istanbul example.

## Why this package

Local flight clocks are not timestamps. A flight can cross midnight, timezones,
or a DST transition; a delay can exceed 24 hours. A cancelled flight can have a
gate-departure observation, and a diverted flight can lack normal arrival fields.
Silently filling dates or dropping these rows makes downstream metrics hard to audit.

FlightOps Quality provides a small reusable layer between raw records and an
analytics warehouse:

- Offset-aware ISO records and a BTS Reporting Carrier CSV adapter.
- DST gap/fold detection, BTS `2400` handling, signed delay and elapsed-time derivation.
- Separate scheduled/actual **gate** times and actual **runway** times.
- Field-level derivation provenance, stable issue codes and raw-record hashes.
- Conflicting identities quarantined as a whole; exact repeats kept in an audit stream.
- Reconciled counts, JSON/JSONL/HTML reports and an explicit OTP denominator.

This complements airport lookup databases, trajectory tools and general schema
validators. See [sources and related work](docs/sources.md) for the research and
limits behind the rules. The opportunity is an explainable operational QA API;
market demand and airline adoption have not been established.

## Run the example

```bash
git clone https://github.com/ubeydgencer/flightops-quality.git
cd flightops-quality
python3 -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
python -m pip install .
flightops-quality examples/synthetic_flights.csv --output example-output
python examples/etl_sqlite.py example-output/audit.json example-output/warehouse.db
```

Open `example-output/audit.html` to inspect each retained record and finding.
The output directory must be new, so reruns preserve earlier audits. The SQLite
example stores all raw rows and accepted unique flights, then executes the
[route KPI SQL](examples/route_metrics.sql). No cloud account or API key is needed.

For the source-specific adapter:

```bash
flightops-quality examples/synthetic_bts.csv --format bts \
  --timezones examples/airport_timezones.json --midnight-policy end --output example-output-bts
```

Supply a current, appropriate airport-to-IANA-timezone mapping for your own BTS
file. The example map covers only three synthetic fixture airports; it is not an
airport database. A **scheduled** `CRSDepTime=2400` needs an explicit `start` or
`end` of `FlightDate` policy, verified for the source release. Without one the
record is unresolved and quarantined. The synthetic fixture deliberately uses
`end`; other actual/arrival clocks are only checked modulo midnight against
duration-derived timestamps. On systems without an IANA timezone database, install
`python -m pip install '.[timezone]'`. Pin Python, OS/tzdata and the mapping when
reproducing historical analysis.

## Python API

```python
from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.batch import analyze_results
from flightops_quality.reporting import audit_document

record = normalize_record({
    "source": "example", "record_id": "leg-1", "service_date": "2026-10-09",
    "carrier": "DEMO", "flight_number": "101", "origin": "IST", "destination": "FRA",
    "sobt": "2026-10-09T09:00:00+03:00", "sibt": "2026-10-09T11:00:00+02:00",
    "aobt": "2026-10-09T08:55:00+03:00", "aibt": "2026-10-09T11:14:00+02:00",
})
report = analyze_results([record])
document = audit_document(report)
assert document["summary"]["arrival_otp_15_completed"]["on_time"] == 1
```

The canonical adapter accepts JSON-compatible mappings. Identity fields and
`service_date` are required; all six timestamp fields are optional. Missing actual
observations on a normal flight produce warnings and no fabricated metrics.
Naive ISO datetimes require `origin_timezone` for `sobt/aobt/atot` and
`destination_timezone` for `sibt/aibt/aldt`. A DST fold needs an explicit
`<field>_fold` of 0 or 1. Offset-aware inputs already identify the instant.

| Field | Meaning |
|---|---|
| `sobt` / `sibt` | Scheduled off-block / in-block (gate) |
| `aobt` / `aibt` | Actual off-block / in-block (gate) |
| `atot` / `aldt` | Actual take-off / landing (runway) |

`flight_metrics(leg)` returns signed gate delays, block, airborne and taxi minutes.
`turnaround_minutes(inbound, outbound)` requires an explicit pair, the same known
aircraft, a matching connecting airport and valid gate times. It does not infer
connections or prescribe a universal minimum turnaround.

## Audit and KPI policy

Every input row appears once in `accepted`, `quarantined` or `duplicates`.
Accepted rows can carry warnings. Exact equality means the same raw JSON payload
under `(source, record_id)`; semantically equivalent but differently encoded
payloads are conservatively treated as conflicts. All rows of a conflicting
identity are quarantined, including repeated members of that group.

`arrival_otp_15_completed` uses only accepted unique, non-cancelled, non-diverted
flights with a valid arrival delay. **Less than 15 minutes** is on time; exactly
15 is late. Missing data, cancellations and diversions are counted separately.
An empty denominator yields `null`, not a misleading zero percent. These are
quality-cohort metrics, not a complete airline performance ranking.

BTS timestamp dates are derived from signed `DepDelay`, `CRSElapsedTime`,
`ActualElapsedTime` and taxi durations, then checked against local clocks. When
evidence is missing the timestamp remains null with a finding. Diverted actual
arrival clocks are not assigned the planned destination timezone. Raw airport and
carrier IDs remain in the audit even though the small canonical model uses codes.

The CLI exits 0 after writing a report, 1 with `--fail-on-error` when rows are
quarantined, and 2 for an unreadable/malformed file or invalid CLI input. It loads
one batch into memory; v0.1 is not a streaming or distributed processor.

## Development

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
ruff check .
python -m build
python -m twine check dist/*
```

See [design and roadmap](docs/design.md), [rule catalog](docs/rules.md) and
[validation evidence](docs/validation.md), plus the [contribution guide](CONTRIBUTING.md).
The MIT license covers this project's
code and original synthetic fixtures; upstream data and specifications retain
their own terms. Releases are distributed on GitHub; no PyPI publication is
implied by the package name.

For Turkish portfolio guidance, see [how to present the project](docs/portfolio-tr.md).
