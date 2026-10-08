# Versioned validation — 9 October 2026

## v0.1.1 security and correctness patch

- **52 unittest cases passed** on CPython 3.9.6 and 3.12.14.
- Three agents independently reviewed security, parsing/lineage and domain/docs.
  Reproduced findings were fixed and rechecked: invalid ISO offset normalization,
  equivalent numeric BTS identities, extreme Decimal exponents, nested JSON keys,
  lone surrogates, mutable input snapshots and blank-line source positions.
- CLI byte/record/cell/column limits, duplicate timezone keys, deep/cyclic API
  input and crafted HTML row numbers have regression coverage.
- Ruff passed. Bandit 1.9.4 reported **no findings** in `src` and `examples`.
- pip-audit 2.10.1 found no known advisories in the audited development tools
  after the project-local pip was upgraded to 26.2.1. The unpublished local project
  itself was skipped by the advisory service; it has zero mandatory runtime
  dependencies. This is not a vulnerability-free certification.
- README API code and local documentation links were verified. The local SVG
  banner was checked as XML. Private vulnerability reporting is enabled on GitHub.

The release additionally checks distribution metadata, fresh-wheel installation,
CLI examples and artifact hashes. Source archive/wheel content is compared with
the published source; text line endings may be normalized by Git.

## v0.1.0 initial snapshot

### Completed local checks

- **38 unittest cases passed** on CPython 3.9.6 and 3.12.14 (macOS).
- `ruff check .` passed with the configured correctness rules.
- Source distribution and universal Python wheel built without build warnings;
  `twine check` passed for both distribution metadata files.
- The wheel installed without runtime dependencies into a fresh Python 3.9
  environment. Both `python -m flightops_quality --version` and the installed
  console command ran outside the source checkout, with no `PYTHONPATH` override.
- The installed wheel's canonical demo accounted for 11 rows: 6 accepted,
  4 quarantined and 1 exact repeat. Its OTP denominator was 2 and OTP was 50%.
- The BTS demo with the explicit synthetic `end` midnight policy accounted for
  5 rows: 4 accepted and 1 quarantined. Two completed flights were OTP eligible.
- SQLite retained all 11 canonical raw rows and 6 accepted unique flights.
  The SQL query independently returned the same 2-flight denominator and 50% OTP.
- A deterministic robustness check processed 1,000 pairs of malformed but
  JSON-compatible canonical/BTS mappings without an unhandled adapter exception.

Tests cover DST fold/gap, explicit offsets, negative delay, overnight timezone
crossing, >24-hour delay, explicit midnight policies, leap/year rollover,
cancellation after gate departure, diverted null arrivals, duration/clock
mismatches, whole-group conflicts, missing identities, exact repeats, explicit
turnaround pairing, KPI exclusions, HTML escaping, source line numbers, malformed
CSV and output preservation.

## Boundaries of this evidence

These are synthetic fixtures and local batch tests. They do not establish
accuracy on a complete historical BTS release, airline production readiness,
performance at large scale, Windows behavior or standards certification.
The reference workflow in `docs/ci.yml` is provided separately; its presence is
not evidence that hosted CI has run. Hosted workflow results, if enabled, should
be read directly from the repository's Actions page.
