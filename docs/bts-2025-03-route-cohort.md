# BTS Reporting Carrier route-cohort validation — March 2025

This benchmark evaluates the March 2025 BTS Reporting Carrier rows whose origin
and destination are both in `{JFK, LAX, ORD}`. The selection uses the entire
monthly source and retains all cancellation and diversion statuses. It is a
dated route cohort, rather than validation of the full monthly dataset or every
airport.

March adds a spring daylight-saving transition to the same route scope used in
[the January benchmark](bts-2025-01-route-cohort.md). Source-field reconstruction,
KPI populations and timezone coverage are reported separately. Agreement with
provider fields does not independently establish absolute UTC dates, timezone
assignments or flight movements.

## Source artifact and extraction

The source is the [March 2025 Reporting Carrier On-Time Performance archive](https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_3.zip)
published by the US Bureau of Transportation Statistics.

| Artifact | Size | SHA-256 |
|---|---:|---|
| Monthly ZIP | 30,544,825 bytes | `9c80fbc2112cdbf3f0613ec2001ba019b3ad75511cd69657080736e7eda9cef4` |
| Source CSV inside the ZIP | 271,623,365 bytes | `ba031a484a67f743869bc1284a09fa1de61cf35a6da010e87674a3dc128590d0` |
| Supplied timezone-map file | — | `22d092c690ba02f79b19424966faae4e238ba73ab17dac3da237f004ec9931f1` |
| Generated `cohort.csv` | — | `7346978c2cf8ae60dc72cd5e5ebec02b8bbe684dfc1ab840e0658b4bbc8738bb` |

The offline validator verifies the expected archive SHA-256, scans and hashes the
complete source CSV, and checks every source `FlightDate` against `2025-03`.
It retains rows satisfying
`Origin in map.keys() and Dest in map.keys()` for batch analysis. There is no
sampling, delay filter or status filter.

All **110 source columns**, including the empty trailing header, remain in the
extracted `cohort.csv`. The CSV member is
`On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2025_3.csv`. An added
`_source_line_number` preserves the original CSV position and is excluded from
normalization and duplicate fingerprints. The original archive and full cohort
are not bundled. This March evidence contains bounded derived offset-window
examples, rather than raw source-row excerpts. The January evidence retains its
separate clock-finding excerpt.

The [BTS field dictionary](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ)
defines the local clocks, signed delays, elapsed/taxi times and status fields used
by the adapter. Archive and CSV hashes identify the dated artifacts used in a
run; the hashes are not provider signatures.

The recipe caps compressed input at 64 MiB, the decompressed CSV at 512 MiB,
source rows at 1,000,000 and columns at 256. The selected cohort is limited to
20,000 rows, 2,000,000 cells and 64 MiB of UTF-8 field values. Exceeded bounds
stop the run rather than publishing a truncated sample.

## Airport identities and timezone context

The mapping is a project-curated inference from reviewed FAA locations and IANA
zone definitions, rather than a direct official IATA-to-IANA airport table.

| Source code | FAA city / state / county | FAA site number | Observed BTS AirportID / AirportSeqID | IANA zone |
|---|---|---|---|---|
| JFK | New York / NY / Queens | `15793.` | `12478` / `1247805` | `America/New_York` |
| LAX | Los Angeles / CA / Los Angeles | `01818.` | `12892` / `1289208` | `America/Los_Angeles` |
| ORD | Chicago / IL / Cook | `04508.` | `13930` / `1393008` | `America/Chicago` |

The airport names, identifiers, locations and coordinates were reviewed in the
`APT_BASE.csv` files from [20 February 2025 NASR](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-02-20/)
and [20 March 2025 NASR](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-03-20/).
For these three airport rows, only the effective-date field differs between the
two snapshots. The dated cycles span the March reporting period. FAA site
numbers and BTS airport IDs are different namespaces; one is not substituted
for the other.

| Reviewed primary artifact | SHA-256 |
|---|---|
| [FAA 20 February 2025 APT ZIP](https://nfdc.faa.gov/webContent/28DaySub/extra/20_Feb_2025_APT_CSV.zip) | `9fa7d26819c59d231ca34b4e9f4ac736032a0ded257c13535fe9b38bfdb10dfc` |
| [FAA 20 March 2025 APT ZIP](https://nfdc.faa.gov/webContent/28DaySub/extra/20_Mar_2025_APT_CSV.zip) | `f108f95370d47de4ae60d543022222424f33427affc5b368a50fdf6a0e53a61d` |
| [IANA 2025a `northamerica`](https://data.iana.org/time-zones/tzdb-2025a/northamerica) | `bb441456077da404a1997a50abfee95ac11937d9c28278cfe36f85277227c1f1` |

The [IANA 2025a zone catalog](https://data.iana.org/time-zones/tzdb-2025a/zone1970.tab)
and North America rules supply the city-zone context. Applying their US spring
rule gives **9 March 2025** transitions at 07:00 UTC for New York, 08:00 UTC for
Chicago and 10:00 UTC for Los Angeles. The corresponding offsets advance from
−05:00 to −04:00, −06:00 to −05:00 and −08:00 to −07:00. These transition instants
are calculated from the cited rules, not independently observed flight events.
The runtime timezone database is recorded separately from this mapping review.

Original airport IDs, airport sequence IDs, city/state fields, carrier IDs and
`FlightDate` remain visible. BTS recommends AirportID for analysis over years
because airport codes can change or be reused; AirportSeqID identifies attributes
at a particular point in time. The cohort's observed IDs and the dated mapping
sources should be read together.

## View the recorded evidence

The static report presents the committed March evidence without rerunning
normalization:

```bash
python examples/bts_validation_html.py \
  --input docs/evidence/bts-2025-03-route-cohort.json \
  --output bts-report-2025-03.html
```

Open `bts-report-2025-03.html` in a browser. It uses no JavaScript or remote fonts.
Archive/mapping hashes, period, runtime, dispositions, held-out comparison
populations and exclusions, source-input KPIs and diagnostic findings remain
visible together. Choose a new output filename; existing outputs are preserved.
The JSON remains the machine-readable evidence.

The [March HTML report](https://github.com/ubeydgencer/flightops-quality/releases/download/v0.2.3/bts-2025-03-report.html)
and [recorded JSON](https://github.com/ubeydgencer/flightops-quality/releases/download/v0.2.3/bts-2025-03-route-cohort.json)
are release assets. The committed evidence is also available as
[the March route-cohort JSON](evidence/bts-2025-03-route-cohort.json).

## Reproduction

Run from the repository root after installing the package. Download the specified
BTS archive separately, then supply its local path. The validator itself is
offline and does not fetch source data. This external download uses the official
fixed archive URL:

```bash
curl --fail --location \
  'https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_3.zip' \
  --output bts-2025-03.zip
```

```bash
python -m pip install 'tzdata==2025.1'
PYTHONTZPATH='' python examples/validate_bts_month.py \
  --archive bts-2025-03.zip \
  --expected-sha256 9c80fbc2112cdbf3f0613ec2001ba019b3ad75511cd69657080736e7eda9cef4 \
  --period 2025-03 \
  --source-url 'https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_3.zip' \
  --timezones examples/airport_timezones.json \
  --output bts-validation-2025-03
```

Choose a new output directory. `--source-url` records a provenance label; it does
not initiate a download. Preserve the archive and all generated artifacts for
repeatable analysis.

The recorded v0.2.3 run used CPython **3.12.14** on macOS and
`tzdata==2025.1`, containing IANA **2025a**. Select the same Python environment
for replay. The [tzdata release notes](https://github.com/python/tzdata/blob/master/NEWS.md)
document the package-to-IANA release relationship.

Set `PYTHONTZPATH=''` before starting Python to use the pinned tzdata package
instead of the system search path. Merely installing tzdata does not establish
which rules ZoneInfo used. The report records the package/IANA versions and
timezone search paths.
The recorded `timezone_system_search_paths` list is empty.

A completed run writes `validation.json`, `validation.html` and `cohort.csv` as
one evidence directory. Exit 0 means that directory was written, even when
findings or reconstruction mismatches remain in the evidence. Invalid source or
configuration exits 2 without publishing a partial directory. Input limits fail
instead of truncating the cohort.

No scheduled-midnight anchor or DST fold is guessed. A scheduled `2400` without
a reviewed date policy remains unresolved. Nonexistent local departure clocks
are findings, and ambiguous clocks require explicit source evidence.

## Source-field reconstruction and KPI accounting

Original rows determine accepted, quarantined and exact-repeat dispositions as
one batch. A separate probe withholds `ArrDelay` and `AirTime`, reconstructs the
corresponding metrics from the remaining schedule, signed departure delay,
elapsed and taxi evidence, then compares them with the withheld values.

Each held-out comparison partitions all selected rows into checked records and
explicit exclusion reasons. Checked records are split into matches and
mismatches. Cancellations, diversions, missing or invalid targets, probe errors
and unresolved predictions must not silently count as matches.

Source-input KPI accounting reads the reported signed `ArrDelay` for both the
whole source cohort and the accepted unique population. Accepted-source parity
compares that latter population with the package summary. It checks accounting
and denominator policy, rather than independently testing reconstruction of a
field that also participated in original-row validation.

Arrival OTP counts delay **below 15 minutes** as on time; exactly 15 is late.
Arrival coverage divides eligible accepted normal flights by all accepted normal
flights, including those missing arrival delay. Quarantine rate uses accepted plus
quarantined records and excludes exact repeats. See
[quality gates](quality-gates.md) for the formulas and empty-population behavior.

## Observed results

The source scan covers **1–31 March 2025**, reads **600,872 source rows** and
selects **3,079** using only the two-airport membership predicate.

| Cohort accounting | Rows |
|---|---:|
| Selected source rows | 3,079 |
| Accepted unique rows | 3,079 |
| Quarantined rows | 0 |
| Exact repeats | 0 |
| Source cancelled flights | 9 |
| Source diverted flights | 9 |
| Accepted normal flights with usable arrival delay | 3,061 |

| Selected route | Rows |
|---|---:|
| JFK → LAX | 836 |
| JFK → ORD | 133 |
| LAX → JFK | 838 |
| LAX → ORD | 570 |
| ORD → JFK | 133 |
| ORD → LAX | 569 |

No normalizer issues or unresolved reconstructions were recorded in this cohort.
Expected absent actual fields in cancelled or diverted rows remain explicit in
the source-missing-field counts. Acceptance of those rows does not make their
normal destination-arrival metrics eligible.

The held-out checks account for **every selected source row**:

| Held-out source field | Compared | Matched | Mismatched | Cancelled | Diverted |
|---|---:|---:|---:|---:|---:|
| `ArrDelay` | 3,061 | 3,061 | 0 | 9 | 9 |
| `AirTime` | 3,061 | 3,061 | 0 | 9 | 9 |

For each field, `3,061 + 9 + 9 = 3,079`. There are no additional missing-target,
probe-error or unresolved exclusions in this run. The zero-mismatch result
applies to **3,061 comparable normal rows**, not all 3,079 flights.

### Metrics and denominators

| Arrival OTP population | Eligible | On time | Late | OTP |
|---|---:|---:|---:|---:|
| Selected source normal rows, using reported `ArrDelay` | 3,061 | 2,584 | 477 | 84.4169% |
| Accepted unique normal rows, using reported `ArrDelay` | 3,061 | 2,584 | 477 | 84.4169% |
| Package summary for accepted unique normal rows | 3,061 | 2,584 | 477 | 84.4169% |

All six accepted-source parity fields agree: eligible population, coverage
population, on-time count, late count, OTP and arrival coverage. The source and
accepted populations coincide here because there are no quarantines or repeats;
they remain separate calculations. Agreement is source-input accounting, not a
second held-out reconstruction test or a national BTS KPI claim.

Accepted arrival coverage is **100%** (`3,061 / 3,061`). Quarantine rate is **0%**
(`0 / (3,079 + 0)`). These are observed data-quality and selected-route metrics.

## Interpreting timezone coverage

Offset diagnostics use the original batch's accepted unique flights and already
resolved timestamps. Scheduled windows are **SOBT → SIBT** for all statuses,
including cancellation and diversion. Actual windows are **AOBT → AIBT** for
accepted non-cancelled, non-diverted flights only. Quarantined records and exact
repeats are excluded from both populations.

For each window, each distinct origin/destination IANA zone is compared **with
itself at both UTC endpoints**. This does not compare the origin's offset with
the destination's offset. A shared zone counts once. `offset_change_rows` counts
flight windows with at least one endpoint-offset difference;
`zone_change_observations` counts changed zones within those windows.

| Window | Population | Checked | Missing endpoints | Windows with an offset change | Changed-zone observations |
|---|---:|---:|---:|---:|---:|
| Scheduled, accepted unique all-status | 3,079 | 3,079 | 0 | 15 | 23 |
| Actual, accepted unique normal | 3,061 | 3,061 | 0 | 18 | 25 |

The evidence keeps up to ten changed-window examples for each population. These
examples are bounded diagnostics, not the complete set of changed windows.

For example, source CSV line **199**, service date **8 March 2025**, LAX → JFK,
has a derived actual window from **9 March 05:57 UTC to 11:20 UTC**. Converting
both endpoints separately into each airport zone produces:

| Zone | Local representation of window start | Local representation of window end | Offset change |
|---|---|---|---|
| `America/Los_Angeles` | 8 March 21:57 −08:00 | 9 March 04:20 −07:00 | +60 minutes |
| `America/New_York` | 9 March 00:57 −05:00 | 9 March 07:20 −04:00 | +60 minutes |

This is one changed flight window and two changed-zone observations. The local
representations describe the same two UTC endpoints in each zone; they do not
assert the aircraft was at both airports at each endpoint.

Endpoint differences show which runtime offset paths were exercised. They do
not independently prove the source's date anchor, absolute UTC instants or
timezone assignment. An offset change is not necessarily daylight saving in a
general historical dataset. Only endpoints are compared, so multiple changes
that cancel out within a window can be missed.

A month spanning the spring transition does not imply that every transition
edge case appears in the selected routes. Schedule and actual observations can
also have different local dates or offsets. The evidence must distinguish
resolved observations from missing or rejected values.

## Limits of this evidence

This route cohort supplements the January benchmark and synthetic edge-case
tests. It does not establish complete-month/all-airport accuracy, autumn DST-fold
coverage, a general historical airport resolver or airline production readiness.
The underlying row ruleset remains **0.1.1**; benchmark diagnostics do not change
record acceptance rules or repair reported source fields.

Independent absolute UTC evidence, other airports and periods, source revisions
and consumer feeds require separate validation. The package remains a batch
alpha with explicit uncertainty and consumer-selected data-quality policy.
