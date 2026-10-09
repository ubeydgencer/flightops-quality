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
- API raw data is copied recursively, with string keys at every level, valid
  UTF-8 strings, finite numeric values, at most 32 nesting levels and integers
  of at most 4096 bits. Cycles and non-JSON objects fail with `ValueError`.
- All report text, including crafted row numbers, is HTML-escaped. Reports have
  no JavaScript or remote assets. Raw payloads are preserved in local outputs;
  those outputs can contain confidential data. The CLI stages outputs in a
  private directory with mode 0700 on POSIX, then publishes with an exclusive
  rename. Missing native support fails without a partial final audit. Use
  appropriate access controls and retention when moving or sharing reports.
- The SQLite example binds all input values as SQL parameters. It creates a new
  private staged database and publishes without replacing an existing path only
  after inserts and the metric query succeed. A failed quality gate blocks
  loading unless the caller explicitly requests and records an override.
- Batch thresholds reject nonfinite percentages, boolean values and invalid
  counts. Policy and result are audit metadata, not signed authenticity evidence;
  the SQLite example expects an audit from a trusted local pipeline.

The CLI is a local batch tool, not an authenticated web service. Service wrappers
must enforce their own request/concurrency limits, access control and retention.
Direct API callers must also bound overall payload/record sizes; CLI caps are not
an automatic limit on every library call. Existing report objects should be
treated as read-only snapshots.

## Validation limits

Unit tests, independent code review, static analysis and dependency advisory
checks provide evidence, not a guarantee of absence of vulnerabilities. See
[versioned validation](docs/validation.md). The optional CI reference has read-only
repository permissions and no publish secrets; it is not enabled with the
currently available GitHub integration permissions.
