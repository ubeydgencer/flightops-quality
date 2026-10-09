# Batch quality gates

Quality gates answer whether a batch meets the consumer's declared data-quality
requirements before warehouse loading. They do not change row dispositions,
repair missing observations or impose an airline performance target. Thresholds
are chosen by the caller; they are not flight-safety or aviation certification
standards.

## Measurements and populations

| Measurement | Numerator / denominator | Meaning |
|---|---|---|
| Arrival coverage percent | OTP-eligible flights / accepted unique normal flights × 100 | How much of the accepted normal-flight cohort has a usable arrival delay. |
| OTP-eligible flights | Count of accepted unique, non-cancelled, non-diverted flights with a valid arrival delay | Size of the population available for arrival OTP analysis. |
| Quarantine rate percent | Quarantined records / (accepted records + quarantined records) × 100 | Share of the evaluated record population rejected by quality rules or identity conflicts. |

An accepted normal flight is neither cancelled nor diverted. The arrival-coverage
denominator is `eligible + missing arrival delay`; cancelled and diverted flights
are excluded. With no accepted normal flights, coverage is `null`. A configured
minimum coverage check then fails, even if its threshold is zero: an undefined
measurement does not demonstrate coverage.

The quarantine rate is also `null` when its denominator is zero; a configured
maximum then fails. Eligible-flight count remains zero, so a minimum count of
zero passes even for an empty batch.

Exact-repeat records are excluded from the quarantine-rate denominator. Every
member of a conflicting identity is quarantined and counted there, including
repeated members of that conflict group. This is a record-level quality measure;
it is not a rate of distinct scheduled services.

Coverage and OTP are different. Coverage asks whether the arrival data exists;
OTP asks how often an eligible flight arrived less than 15 minutes late. A batch
can have high OTP and poor coverage. This gate does not set an OTP percentage
target.

## Policy and boundaries

`QualityPolicy` supports three optional thresholds:

| API field | CLI flag | Passing condition |
|---|---|---|
| `min_arrival_coverage_percent` | `--min-arrival-coverage-percent` | Defined coverage `>=` minimum. |
| `min_otp_eligible_flights` | `--min-otp-eligible-flights` | Eligible count `>=` minimum. |
| `max_quarantine_rate_percent` | `--max-quarantine-rate-percent` | Defined quarantine rate `<=` maximum. |

Boundaries are inclusive. Percentages must be finite values between 0 and 100.
Minimum counts must be integers between 0 and `2**63 - 1`. Invalid policy values
are configuration errors, rather than failed data checks.

With no thresholds, the result is `not_configured`. With at least one threshold,
all configured checks must pass for `passed`; otherwise the result is `failed`.
Unconfigured checks do not block a batch.

## A deliberately failing synthetic example

Run from the repository root after installing the package:

```bash
flightops-quality examples/synthetic_flights.csv --output quality-review \
  --min-arrival-coverage-percent 80 \
  --min-otp-eligible-flights 10 \
  --max-quarantine-rate-percent 5
```

This command intentionally exits **1**. It still writes `quality-review/audit.json`,
HTML and the disposition JSONL files so the failure remains inspectable. The
synthetic fixture contains:

| Population / measurement | Value |
|---|---:|
| Input records | 11 |
| Accepted records | 6 |
| Quarantined records | 4 |
| Exact repeats | 1 |
| Accepted normal flights | 3 |
| OTP-eligible flights | 2 |
| Accepted normal flights missing arrival delay | 1 |
| Arrival coverage | 2 / 3 ≈ 66.67% |
| Quarantine rate | 4 / (6 + 4) = 40% |
| Arrival OTP for eligible flights | 1 / 2 = 50% |

All three configured checks fail. Two cancelled flights and one diverted flight
are excluded from the normal-flight population. Coverage and OTP use different
numerators and denominators. These numbers are synthetic policy demonstrations,
not airline results.

`audit.json` contains a top-level `quality_gate` object with `status`, `policy`,
`measurements` and `checks`. Read the measured values and individual checks
alongside the raw records and findings, rather than inspecting the status alone.

`measurements.arrival_coverage_percent` and
`measurements.quarantine_rate_percent` each expose `value`, `numerator`,
`denominator` and a human-readable `population`. The eligible-count measurement
has `value` and `population`. Each configured check records `metric`, `operator`,
`threshold`, `observed`, `passed` and `reason`. The summary's
`arrival_otp_15_completed.coverage_population` and `coverage_percent` expose the
same arrival-coverage population and percentage alongside OTP.

## Python integration

```python
import csv

from flightops_quality import QualityPolicy, analyze_records, evaluate_quality
from flightops_quality.reporting import audit_document

with open("examples/synthetic_flights.csv", newline="", encoding="utf-8") as handle:
    report = analyze_records(csv.DictReader(handle))

policy = QualityPolicy(
    min_arrival_coverage_percent=80,
    min_otp_eligible_flights=10,
    max_quarantine_rate_percent=5,
)
gate = evaluate_quality(report, policy)
document = audit_document(report, quality_policy=policy)
assert document["quality_gate"]["status"] == "failed"
```

`evaluate_quality(report)` evaluates an unconfigured policy. Reuse the same
policy in `audit_document` so the exported audit matches the pipeline's decision.
API callers decide how a failed result affects their own job; the function does
not load a warehouse or terminate a process.

## CLI and warehouse behavior

| Condition | CLI result |
|---|---|
| No configured thresholds, no `--fail-on-error` rejection | Report written; exit 0, including batches with quarantined rows. |
| All configured thresholds pass | Report written; exit 0 unless `--fail-on-error` rejects quarantined rows. |
| Any configured threshold fails | Report written; exit 1. |
| `--fail-on-error` and at least one quarantined row | Report written; exit 1. |
| Invalid policy or malformed input | Exit 2 before audit output is created. |

Omitting the new flags preserves the earlier CLI behavior. Existing output
directories are still refused to preserve previous audits.

The SQLite example blocks a failed quality gate by default:

```bash
python examples/etl_sqlite.py quality-review/audit.json quality-review/warehouse.db
```

After a deliberate review, an exploratory load can use the explicit override:

```bash
python examples/etl_sqlite.py quality-review/audit.json quality-review/reviewed.db \
  --allow-failed-quality-gate
```

The override permits loading accepted records; it does not accept quarantined
records, change the recorded gate result or make the batch suitable for every
analysis. All raw rows remain in the audit/warehouse example. Audits with an absent
or `not_configured` quality gate retain the legacy loading behavior.

Python callers can use `load(audit_path, database_path,
allow_failed_quality_gate=True)` for the same reviewed override; its default is
`False`. Database publication requires a filesystem supporting hard links and
refuses an existing destination. The example's `audit_metadata` table retains the
quality-gate result and whether the failed-gate override was used.

Warehouse input limits apply independently of quality-gate status. By default,
the loader bounds the UTF-8 JSON snapshot to 128 MiB before decoding and the total
accepted + quarantined + duplicate population to 100,000 observations before
digest checks or reconstruction. Trailing whitespace and file growth count
toward the byte limit. Input must be a regular file; symlinks to regular files
are allowed, and POSIX FIFOs are rejected without waiting for a writer.

For trusted larger audits, pass `max_audit_bytes=268435456, max_records=200000`
to `load`, or `--max-audit-bytes 268435456 --max-records 200000` to the example CLI.
These values allow 256 MiB and 200,000 observations. Limits must be positive,
non-boolean integers up to `2**63 - 1`; invalid limits or exceeded bounds prevent
output creation. The failed-gate override cannot bypass them. JSON parsing and
normalization remain in memory, so these are not hard memory, CPU-time or
concurrency limits.

Before any database is created, all accepted, quarantined and duplicate raw
records must match their stored SHA-256 digests. The loader uses the producer's
canonical JSON serialization, so whitespace and object-key order do not affect
the digest. Duplicate JSON object keys are rejected throughout the audit rather
than choosing a value. These checks still apply with a manual failed-gate
override and to legacy audits without a `quality_gate` field.

This verifies internal raw-record consistency. It does not authenticate the
audit author or compare against the original source file, and the loader does
not re-normalize provider rows with a potentially different timezone database.
Supply audits from your trusted local pipeline.

The loader independently reconstructs `summary` from the accepted normalized
timestamps/statuses and recorded findings across all dispositions. Counts,
arrival OTP and coverage populations, exclusions, accepted cancellation/diversion
rates and finding-occurrence counts must agree before loading. Finding counts
include every occurrence, so repeated codes within one row contribute more
than one. The supplied summary is preserved in `audit_metadata.summary_json`
after verification; it is not silently corrected. A passed gate or manual
failed-gate override cannot bypass this check.

Known v0.1.0/v0.1.1 audits without a `quality_gate` may omit both
`coverage_population` and `coverage_percent` together, as those producers did.
All other summary fields are still checked. Omitting only one, using an unknown
producer version or removing these fields from a modern summary is rejected.

See [the rule catalog](rules.md) for row findings, [design](design.md) for identity
and provenance policies, and [validation](validation.md) for the limits of the
synthetic evidence.
