# Security policy

## Supported version

Use the latest release. The project is an alpha batch library; old alpha
versions do not receive separate backports. Use a maintained Python interpreter
and timezone database even though the compatibility floor is Python 3.9.

## Reporting a vulnerability

Private vulnerability reporting is enabled. Use
[Report a vulnerability](https://github.com/ubeydgencer/flightops-quality/security/advisories/new)
and include the affected version, a minimal synthetic reproduction, impact and
expected behavior. Do not post exploit details or sensitive data in a public
issue. Do not send real passenger data, credentials or private airline feeds.
There is no guaranteed response deadline for this independently maintained project.

## Trust boundary and controls

- The package has no network clients, subprocess execution, SQL string
  interpolation, pickle/eval deserialization or mandatory runtime dependencies.
- CLI CSV input defaults to 50 MiB, 100,000 records and 2,000,000 cells. Headers
  are limited to 256 columns; timezone JSON is limited to 1 MiB. The CSV parser
  also applies Python's field-size limit. Bounds are checked before audit files
  are created; raise configurable limits deliberately for trusted batches.
- Timezone maps reject duplicate JSON keys. Source-file hashes and parsing use
  the same bounded byte snapshot.
- The offline BTS benchmark snapshots at most 64 MiB of ZIP bytes, requires an
  expected SHA-256 and reads a single CSV without extracting archive paths.
  Decompressed bytes (512 MiB), source rows (1 million), retained rows (20,000),
  cells (2 million) and retained UTF-8 values (64 MiB) are bounded separately.
  Wrong periods, malformed rows, CRC failures or exceeded bounds prevent output
  publication. A source URL is a label; it initiates no network request. Generated
  cohort CSVs preserve source values; use an importer that treats them as text
  rather than executing spreadsheet formulas in untrusted input.
- API raw data is copied recursively, with string keys at every level, valid
  UTF-8 strings, finite numeric values, at most 32 nesting levels and integers
  of at most 4096 bits. Cycles and non-JSON objects fail with `ValueError`.
- All report text, including crafted row numbers, is HTML-escaped. Reports have
  no JavaScript or remote assets. Raw payloads are preserved in local outputs;
  those outputs can contain confidential data. The CLI stages outputs in a
  private directory with mode 0700 on POSIX, then publishes with an exclusive
  rename. Missing native support fails without a partial final audit. Use
  appropriate access controls and retention when moving or sharing reports.
- The benchmark HTML viewer accepts at most 2 MiB of JSON, rejects duplicate keys
  and inconsistent count/percentage populations, and escapes every displayed
  source value. Its CSP permits only the fixed stylesheet by hash; no scripts,
  remote assets or source-URL links are included. Standalone HTML publication
  uses a private staged file and exclusive hard link; that filesystem operation
  must be supported. The view records its input-byte hash but does not authenticate
  the JSON's author or rerun flight normalization.
- The SQLite example binds all input values as SQL parameters. It creates a new
  private staged database and publishes without replacing an existing path only
  after inserts and the metric query succeed. A failed quality gate blocks
  loading unless the caller explicitly requests and records an override.
- SQLite audit input defaults to 128 MiB of UTF-8 JSON bytes and 100,000 total
  observations across accepted, quarantined and duplicate records. The byte
  snapshot rejects oversized input, including trailing whitespace or growth
  during reading, before JSON decoding. The observation count is bounded before
  digest checks and report reconstruction. Only regular files are accepted;
  symlinks to regular files are allowed, while POSIX FIFOs are rejected without
  waiting for a writer. `max_audit_bytes` / `max_records` and their CLI flags
  accept positive, non-boolean integers up to `2**63 - 1`. Invalid limits fail
  before output creation; a failed-gate override cannot bypass these bounds.
- Before creating a database, the SQLite example verifies every raw record's
  SHA-256 against its finite UTF-8 JSON snapshot using the producer's canonical
  serialization. Duplicate JSON object keys are rejected at every level. A
  manual failed-gate override cannot bypass these consistency checks. A digest
  is not a signature: changing both the payload and its digest can still produce
  consistent input. This does not authenticate the author, re-read the original
  source file or re-normalize raw provider records.
- The loader reconstructs summary counts, accepted-cohort metrics and finding
  occurrences from the normalized flights and validated recorded findings.
  A contradictory summary is rejected before database creation, even if the
  gate passed or a failed gate was manually overridden. Findings are checked
  for their recorded shape, severity and UTF-8 text; they are not regenerated.
  Only the known v0.1 no-gate shape may omit both original coverage fields.
- Batch thresholds reject nonfinite percentages, boolean values and invalid
  counts. Policy and result are audit metadata, not signed authenticity evidence;
  the SQLite example expects an audit from a trusted local pipeline.

The CLI is a local batch tool, not an authenticated web service. Service wrappers
must enforce their own request/concurrency limits, access control and retention.
Direct API callers must also bound overall payload/record sizes; CLI caps are not
an automatic limit on every library call. Existing report objects should be
treated as read-only snapshots. Audit JSON can expand substantially relative to
source CSV. SQLite input limits are separate from the producer's CSV limits and
may be raised explicitly for trusted batches. Parsing and normalization remain
in memory; byte caps are not hard limits on memory use, CPU time or concurrency.

## Validation limits

Unit tests, independent code review, static analysis and dependency advisory
checks provide evidence, not a guarantee of absence of vulnerabilities. See
[versioned validation](docs/validation.md). The optional CI reference has read-only
repository permissions and no publish secrets; it is not enabled with the
currently available GitHub integration permissions.
