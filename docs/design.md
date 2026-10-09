# Design and bounded roadmap

## Data flow

```text
raw CSV + caller timezone map
    -> source adapter -> UTC FlightLeg + findings + provenance
    -> identity groups -> accepted / quarantined / exact repeats
    -> batch coverage + caller-selected quality gates
    -> audit JSON + HTML + JSONL -> gated SQLite warehouse -> explicit-cohort SQL
```

No provider fetches, credentials or network access are built into the core.
Adapters retain every original field; a rejected row remains inspectable.
Identity and timestamp policies are deliberately conservative.

The CLI manifest records file and timezone-map hashes, format and timezone
environment. Each row has its original CSV row number, raw payload hash,
normalized values, findings and derivation input field names. Package and
ruleset versions are recorded at the document level. Reproduction also requires
pinning the Python/OS timezone database; the manifest cannot identify an OS
database version portably and does not pretend otherwise.
API callers should put their source URL, timezone-map hash, `midnight_policy`
and any per-record fold choices in the optional `audit_document(..., manifest=...)`
context. The adapter's provenance lists derivation inputs; it is not a complete
environment snapshot by itself.

## Decisions

- Standard-library core keeps integration small. SQLite is the runnable warehouse
  example; Parquet and DuckDB adapters can be added after the API is stable.
- UTC timestamps are separate from the service date. A delayed flight does not
  become a different scheduled service when it departs the next day.
- Derive dates from durations/delays rather than guessing a day from clock order.
- Require caller choice for the scheduled `2400` date anchor; retain that choice
  in the CLI manifest. The BTS directive defines the clock encoding, but this
  alpha does not assume an unvalidated source-release service-date convention.
- Distinguish missing/ambiguous data from values that fail a rule. Warnings can be
  accepted but cannot create a metric without the required observations.
- Exact raw repeats are audited; different payloads with one identity have no
  silent winner. Consumers must explicitly resolve such conflicts upstream.
- Cancelled/diverted cohorts are retained and excluded from normal arrival OTP.
- Arrival-data coverage is a separate measurement from OTP. Coverage counts
  observed delays over accepted unique non-cancelled, non-diverted flights;
  OTP counts on-time flights over that cohort's observed delays. The first is a
  data-availability signal and the second is an operational observation.
- Batch quality thresholds are opt-in consumer requirements, recorded alongside
  their populations, observed values and reasons. They do not assert an airline
  standard. An empty percentage population cannot pass a configured threshold.
- Exact repeats cannot inflate the quarantine-rate denominator. Every member of
  a conflicting identity group stays in that denominator as quarantined.
- Turnaround requires an explicitly supplied valid flight pair; tail swaps,
  diversion and airport mismatch need upstream reconciliation.

## Output publication

The CLI writes every artifact to a private staging directory before publishing
it with an exclusive rename. It uses the operating system's no-replacement
primitive: [Apple's `RENAME_EXCL` definition](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h)
or [Linux `renameat2` with `RENAME_NOREPLACE`](https://man7.org/linux/man-pages/man2/rename.2.html).
Unavailable primitives produce an error; the tool does not fall back to a rename
that could replace an existing empty directory. This prevents a write failure
from presenting an incomplete audit as the final output. It does not promise
power-loss durability or turn a shared writable parent directory into an access
control boundary.

The warehouse example similarly builds a private temporary SQLite file, runs
the route query and closes the connection before publishing. A hard link creates
the final name without replacing an existing path, then the temporary name is
removed. The filesystem must support hard links. Internal `audit_record_id`
values link normalized flights to raw records; source `row_number` values are
preserved as positions and need not be unique for API-produced audits.

Warehouse input has separate bounds because audit JSON expands relative to its
source CSV. The loader snapshots at most 128 MiB by default before JSON decoding,
including trailing whitespace and any bytes added during reading. It accepts
regular files, including symlinks to regular files; POSIX FIFOs fail without
waiting for a writer. The combined accepted, quarantined and duplicate population
is limited to 100,000 observations before digest checks or report reconstruction.
Callers can change `max_audit_bytes` and `max_records` using positive, non-boolean
integers up to `2**63 - 1`, or the matching CLI flags. Bounds are validated before
output creation and apply even when a failed quality gate is overridden. Parsing
and normalization still retain data in memory; these caps are not hard memory,
CPU-time or concurrency limits.

Loading first verifies every raw snapshot against its stored SHA-256 using the
same sorted-key, compact UTF-8 JSON format as `audit_document`. Duplicate JSON
object keys and inconsistent raw digests prevent database creation, including
when a failed quality gate is explicitly overridden. This does not authenticate
the audit author or check raw-to-normalized derivations again; the normalized
timestamps are retained and stored KPIs are independently reconstructed.

The recorded summary is also reconstructed before loading. Findings are retained
in every disposition so `issue_counts` counts occurrences, including repeated
codes in one record; it is not a count of distinct affected rows. Accepted
timestamps and status flags determine OTP, coverage and exclusion populations.
The supplied summary must agree and is preserved unchanged in metadata. The
only legacy projection permits both absent coverage fields for known v0.1
producers without a quality gate; other supplied summary fields are checked.

## Limits and next steps

v0.2 is a batch alpha, tested on synthetic edge cases. It has not been validated
against a full historical BTS release or an airline's production feed. Arrival
clock-only records, diversion itineraries, multiple gate departures and revisions
remain unresolved rather than guessed. Codes in supplied airport maps can change
historically; raw official IDs are preserved but no historical resolver is bundled.

Next steps should follow real usage: compare a dated BTS month with official
totals, add optional columnar exports, and version provider schemas. A future
event reducer would need distinct occurred/received timestamps and source
revision rules; monthly BTS snapshots do not establish streaming behavior.
