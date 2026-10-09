# Versioned validation — 9 October 2026

## v0.2.0 batch quality gates and warehouse integrity

- **96 unittest cases passed** on CPython 3.9.6 and 3.12.14 on macOS.
- Sparse-arrival fixtures distinguish 100% OTP from 1% observation coverage.
  Tests cover empty/all-missing/cancelled/diverted cohorts, inclusive thresholds,
  nonfinite/boolean/invalid policy values and exact-repeat denominator inflation.
- Independent SQLite route SQL agrees with the Python OTP and coverage
  populations. Stored KPI values are reconstructed from normalized timestamps;
  contradictory gate measurements or decisions are rejected, even with an
  explicit failed-gate override.
- Injected HTML, JSONL, SQLite insertion, route-query and publication failures
  leave no partial final artifact and allow retry. Existing empty directories,
  files and dangling symlinks survive publication collisions. Native exclusive
  directory publication was exercised on macOS; Linux and Windows runtime
  behavior has not been validated on this host.
- The warehouse retains raw source positions, independent record IDs, foreign
  key lineage, normalized flight fields, provenance, audit versions and the
  quality-gate result/override. Two API records sharing source row number 1 load
  with separate lineage IDs.
- Three agents reviewed the feature and documentation. A reproduced mismatch
  between a gate's own values and the actual records was fixed and rechecked.
- Ruff passed. Bandit reported **no findings** in `src` and `examples`; the
  development-tool advisory audit reported no known vulnerabilities. The local
  editable project was skipped by that advisory service, and the core still has
  no mandatory runtime dependencies.
- README and quality-gate Python examples ran successfully; CLI/ETL examples,
  local documentation links and the professional Turkish usage guide were
  checked against the current synthetic fixtures.

The package version is 0.2.0; the row ruleset remains 0.1.1. Batch policy is
recorded separately in each audit. These results are local evidence, not hosted
CI results or validation of a real historical flight dataset.

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
