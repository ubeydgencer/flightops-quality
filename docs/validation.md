# Versioned validation — 9 October 2026

## v0.2.4 autumn-transition source cohort

- **193 unittest cases passed** on CPython 3.9.6 and 3.12.14 on macOS.
  Release validation also exercises the suite with freshly installed wheels
  outside the repository and replays the dated source with the pinned runtime.
- The complete November source scan reads 570,550 rows and retains 3,246
  JFK/LAX/ORD observations. The batch accepts 3,245 rows, quarantines one
  ambiguous scheduled departure and finds no exact repeats. Each held-out field
  matches 3,152 comparable observations, with 87 cancellation, six diversion
  and one `dst_ambiguous` exclusions that reconcile to the selected population.
- The observed NK1332 LAX departure at 01:20 on 2 November remains unresolved
  because the benchmark supplies no fold. Its signed arrival-delay label still
  belongs to source-input accounting. Raw source and accepted KPI populations
  differ by that one row; accepted-source parity agrees on all six metrics.
- Endpoint diagnostics record 16 scheduled windows / 23 changed-zone observations
  and 14 actual windows / 20 observations, with no missing endpoints in either
  accepted population. A separate calculation using IANA's 2 November transition
  instants reproduces these counts without calling the coverage helper.
- Two synthetic integration regressions distinguish both occurrences of an
  actual 01:30 clock using a unique scheduled anchor plus signed departure delay.
  They also retain quarantine and empty coverage for an ambiguous scheduled
  anchor. A real-source diagnostic regression reproduces null gate/runway
  timestamps from the bounded NK1332 excerpt. The report regression checks
  backward changes, the explicit ambiguous exclusion and separate populations.
- FAA 30 October / 27 November snapshots review the same airport identities and
  locations. Runtime remains pinned to tzdata 2025.1 / IANA 2025a with an empty
  system search path. January and March evidence remains byte-for-byte unchanged.
- Ruff and Bandit passed with no findings. Development-tool versions match the
  same-day v0.2.3 advisory evidence (47 audited tools, no known advisories at that
  audit); no new dependency audit or whole-package security certification is
  claimed. Local project metadata was skipped by the advisory service.

The [November method and results](bts-2025-11-route-cohort.md) and
[machine-readable evidence](evidence/bts-2025-11-route-cohort.json) document the
route cohort. Real backward-offset windows and the quarantined anchor do not
establish coverage of both actual-departure fold occurrences. The core API and
row ruleset 0.1.1 remain unchanged. Verification is local; hosted CI and PyPI
publication remain unavailable with current access.

## v0.2.3 spring-transition source cohort

- **189 unittest cases passed** on CPython 3.9.6 and 3.12.14 on macOS. The same
  suite is also run from fresh wheel installations outside the checkout before
  publication.
- March 2025 source evidence scans 600,872 rows and retains all 3,079 JFK/LAX/ORD
  observations. No original row is quarantined or repeated. Each held-out field
  matches 3,061 comparable observations; nine cancelled and nine diverted rows
  are explicit exclusions, not matches. Accepted arrival coverage is 100%; OTP
  is 84.4169% with 2,584 on-time and 477 late observations.
- Derived endpoint coverage compares each airport zone with itself over accepted
  unique flight windows. Scheduled windows include cancellation/diversion;
  actual windows use normal flights. The observed changes affect 15 scheduled
  windows / 23 zone observations and 18 actual windows / 25 zone observations.
  A separate count using the dated IANA transition instants agrees with all four
  counts; this still depends on the normalized UTC instants.
- Synthetic tests cover spring/fall signed changes, repeated zones, static
  differences between airports, missing endpoints, status/duplicate/quarantine
  populations, bounded examples, invalid maps, naive/reversed timestamps and
  UTC/local representation limits. Endpoint comparison does not detect offset
  changes that compensate inside a longer window.
- HTML tests reject present-null coverage, inconsistent sample/count bounds and
  repeated example identities while allowing distinct records to share a source
  row reference. Source strings remain escaped. The new section was inspected
  at 1280 px and 390 px with no page overflow, CSP errors or remote requests.
- Official FAA February/March cycles and pinned IANA 2025a rules document the
  curated map. The recorded producer uses tzdata 2025.1 with no system search
  paths. January JSON remains byte-for-byte unchanged and its earlier producer
  metadata is preserved.

Ruff and Bandit passed with no findings. The audited development dependencies
had no known advisories; the local v0.2.2 editable metadata was skipped because
it was unavailable on PyPI. No new mandatory runtime dependencies were introduced.
Hosted GitHub Actions and PyPI publication remain unavailable with current
access. Package metadata, source content and public asset digests are checked
before and after publication.

The [dated March method and results](bts-2025-03-route-cohort.md) and
[machine-readable evidence](evidence/bts-2025-03-route-cohort.json) record the
scope. No absolute UTC ground truth, all-airport validation or flight-safety
certification is claimed. The core API and row ruleset 0.1.1 remain unchanged.

## v0.2.2 offline benchmark report

- **166 unittest cases passed** on CPython 3.9.6 and 3.12.14 on macOS, both from
  source and from fresh wheel installations outside the repository.
- The static HTML view displays source/selected counts, mutually exclusive status
  cohorts, raw/accepted/derived OTP populations, held-out comparison exclusions,
  issue-count units, bounded diagnostic examples and recorded artifact/environment
  provenance. Empty denominators are unavailable; inconsistent counts or
  percentages, including a very large integer percentage, produce clear errors.
- Source fields, metadata, issue text, row references, route/zone keys and hashes
  have HTML injection regression coverage. URLs remain escaped text; the page
  contains no scripts or remote assets. Its CSP permits the fixed stylesheet by
  hash. Desktop (1280 px) and mobile (390 px) views were inspected in headless
  Chrome; no page overflow, CSP console errors or external network requests were
  observed. Comparison and diagnostic sections were inspected separately.
- Standalone JSON input is bounded to 2 MiB and rejects duplicate/deep JSON. Tests
  cover existing files/directories/dangling links, same input/output, concurrent
  destination creation, staged write/link failures, descriptor cleanup, retry
  and private 0600 files even under an unrestricted umask.
- The archive validator publishes JSON, HTML and cohort CSV together. Injected
  renderer failure leaves no final directory. Each HTML report records the hash
  of the actual JSON bytes, including its BOM/whitespace or platform line endings.
- A pinned installed-wheel replay of the actual January source retained the
  same source/validation/cohort evidence as v0.2.1, apart from the new producer
  package version. The checked-in v0.2.1 JSON evidence is unchanged; rendering it
  is a view of the earlier run, not a new normalization.
- Ruff and Bandit passed with no findings; audited development dependencies had
  no known advisories. The local editable project was skipped by the advisory
  service. Twine metadata, distribution content and public asset hashes are
  checked for publication. Hosted CI is still unavailable with current access.

The core API and row ruleset 0.1.1 are unchanged. Native output publication and
browser rendering were exercised on macOS; this is not Windows runtime or
flight-safety certification.

## v0.2.1 dated BTS route cohort

- **139 unittest cases passed** on CPython 3.9.6 and 3.12.14 on macOS, both from
  source and with a freshly installed wheel outside the repository.
- The complete January 2025 Reporting Carrier source was scanned and hashed:
  539,747 rows, 243,177,378 decompressed bytes. The preselected JFK/LAX/ORD route
  cohort retains 2,929 source rows, including cancellation and diversion.
- One original batch produces 2,928 accepted rows, one quarantined clock/duration
  contradiction and no exact repeats. Two fields are withheld from a separate
  probe: each of arrival delay and airborne minutes matches 2,909 of 2,909
  comparable source observations. Each check also accounts for 11 cancellations,
  eight diversions and the one clock contradiction; none are counted as matches.
- The pinned replay uses tzdata 2025.1 / IANA 2025a with an empty system search
  path. A clean installed-wheel replay produced exactly the same complete JSON
  evidence and extracted-cohort hash as the recorded source run.
- Source-input OTP uses original signed ArrDelay and records raw-row and accepted
  unique denominators separately. Tests preserve a real missing-target parity
  difference while preventing a false mismatch caused by percentage rounding.
- Archive/CSV checksums and CRC, wrong periods outside the selected cohort,
  malformed headers/rows, trailing unnamed export columns, decompression bounds,
  source/cohort/cell/UTF-8 limits and atomic output failures have regression tests.
  Scheduled midnight and DST folds are never guessed by the benchmark.
- Ruff passed; Bandit reported no findings in `src` and `examples`. The audited
  development dependencies had no known advisories; the local editable package
  was skipped by the advisory service. The core has no mandatory dependencies.
- Distribution metadata passed Twine checks. Release artifacts are checked
  against source content, then verified by SHA-256 after public download.

The [dated recipe, source provenance and observed results](bts-2025-01-route-cohort.md)
and [machine-readable evidence](evidence/bts-2025-01-route-cohort.json) describe
the exact cohort. This is provider-field consistency evidence, not independent
ground truth for absolute UTC dates, full-month/all-airport validation or hosted
CI. The library API and row ruleset remain unchanged; the ruleset is 0.1.1.

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

Synthetic fixtures and local batch tests are supplemented by the dated route
cohort above. They do not establish accuracy on a complete historical BTS release, airline production readiness,
performance at large scale, Windows behavior or standards certification.
The reference workflow in `docs/ci.yml` is provided separately; its presence is
not evidence that hosted CI has run. Hosted workflow results, if enabled, should
be read directly from the repository's Actions page.
