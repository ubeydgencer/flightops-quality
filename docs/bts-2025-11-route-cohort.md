# BTS Reporting Carrier route-cohort validation — November 2025

This recipe evaluates the November 2025 BTS Reporting Carrier rows whose origin
and destination are both in `{JFK, LAX, ORD}`. Selection scans the entire monthly
source and retains all cancellation and diversion statuses. It is a dated route
cohort, rather than validation of the full monthly dataset or every airport.

November adds an autumn timezone-transition period to the route scope used by
the [January](bts-2025-01-route-cohort.md) and
[March](bts-2025-03-route-cohort.md) benchmarks. Source-field reconstruction,
KPI accounting, resolved offset windows and ambiguous local-clock findings are
different measurements. Agreement with provider fields does not independently
establish absolute UTC dates, timezone assignments or actual flight movements.

## Source artifact and extraction

The source is the [November 2025 Reporting Carrier On-Time Performance archive](https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_11.zip)
published by the US Bureau of Transportation Statistics.

| Artifact | Size | SHA-256 |
|---|---:|---|
| Monthly ZIP | 28,847,755 bytes | `6d5b68eea3ebb25f3cb2843e701a6c809b5455301b3bbd7802a20d522ed770c8` |
| Source CSV inside the ZIP | 258,071,953 bytes | `6d6d63f3bb312a6695d4a8b17958bc47e4e71fdf7396ec882c9c9a61faa6efc2` |
| Supplied timezone-map file | — | `22d092c690ba02f79b19424966faae4e238ba73ab17dac3da237f004ec9931f1` |
| Generated `cohort.csv` | — | `a3881c524074a5f007ba09b525364cf997e8e9ecb5bab40701d466d7aa3e8d87` |

The offline validator checks the supplied archive against its expected SHA-256,
scans and hashes the complete source CSV, and checks every source `FlightDate`
against `2025-11`. It retains all rows satisfying
`Origin in map.keys() and Dest in map.keys()` for one batch. There is no sampling,
delay filter or status filter.

All **110 source columns**, including the empty trailing header, remain in the
extracted `cohort.csv`. The member is
`On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2025_11.csv`. An added
`_source_line_number` preserves the original CSV position and is excluded from
normalization and duplicate fingerprints. The original archive and full cohort
are not bundled. Bounded diagnostic examples in versioned evidence must be read
with their recorded source positions and populations. This evidence includes a
bounded raw excerpt for the ambiguous scheduled-departure finding, alongside
derived offset-window examples.

The [BTS field dictionary](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ)
defines the local clocks, signed delays, elapsed/taxi durations and status fields
used by the adapter. Hashes identify the downloaded source, reviewed map and
generated cohort; they are not provider signatures or a promise that the source
will never be revised.

The recipe caps compressed input at 64 MiB, the decompressed CSV at 512 MiB,
source rows at 1,000,000 and columns at 256. The selected cohort is limited to
20,000 rows, 2,000,000 cells and 64 MiB of UTF-8 field values. Exceeded bounds
stop the run rather than publishing a truncated sample.

## Airport identities and timezone context

The supplied map uses `JFK → America/New_York`,
`LAX → America/Los_Angeles` and `ORD → America/Chicago`. It is a project-curated
inference from dated FAA airport locations and IANA zone definitions, rather
than an official direct IATA-to-IANA airport table. Mapping-source provenance
and the timezone database used at runtime are recorded separately.

Original airport IDs, airport sequence IDs, city/state fields, carrier IDs and
`FlightDate` remain visible. BTS recommends AirportID for analysis over years
because codes can change or be reused; AirportSeqID identifies attributes at a
particular point in time. FAA site numbers are a separate namespace and are not
substituted for those BTS identifiers. The three-airport mapping review does
not establish a general historical airport catalog.

| Source code | FAA city / state | FAA site number | Observed BTS AirportID / AirportSeqID | IANA zone |
|---|---|---|---|---|
| JFK | New York / NY | `15793.` | `12478` / `1247805` | `America/New_York` |
| LAX | Los Angeles / CA | `01818.` | `12892` / `1289209` | `America/Los_Angeles` |
| ORD | Chicago / IL | `04508.` | `13930` / `1393008` | `America/Chicago` |

The airport rows in `APT_BASE.csv` were checked in FAA subscriptions effective
[30 October 2025](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-10-30/)
and [27 November 2025](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-11-27/).
For all three airports, the full-row comparison finds only an effective-date
change between snapshots. The cycles span the November reporting period.

| Reviewed primary artifact | Size | SHA-256 |
|---|---:|---|
| [FAA 30 October 2025 APT ZIP](https://nfdc.faa.gov/webContent/28DaySub/extra/30_Oct_2025_APT_CSV.zip) | 8,551,523 bytes | `136f6e57b12f651649f072c949c8ea062e883d9c939aaa8222d1d46e8b004d7d` |
| [FAA 27 November 2025 APT ZIP](https://nfdc.faa.gov/webContent/28DaySub/extra/27_Nov_2025_APT_CSV.zip) | 8,549,337 bytes | `3a9d93f8e3f04b64854fbbf019b7e74cae710c4dfbd556be18b553164f571c83` |
| [IANA 2025a `northamerica`](https://data.iana.org/time-zones/tzdb-2025a/northamerica) | — | `bb441456077da404a1997a50abfee95ac11937d9c28278cfe36f85277227c1f1` |

The [IANA 2025a zone catalog](https://data.iana.org/time-zones/tzdb-2025a/zone1970.tab)
and [North America rules](https://data.iana.org/time-zones/tzdb-2025a/northamerica)
provide the city-zone context and US autumn rule. Applying that rule gives these
**2 November 2025** transitions:

| IANA zone | Calculated transition UTC | Offset before | Offset after |
|---|---|---|---|
| `America/New_York` | 06:00 | −04:00 | −05:00 |
| `America/Chicago` | 07:00 | −05:00 | −06:00 |
| `America/Los_Angeles` | 09:00 | −07:00 | −08:00 |

For each zone, local times from **01:00 inclusive to 02:00 exclusive** occur
twice. Fold 0 denotes the earlier daylight-time occurrence and fold 1 the later
standard-time occurrence. These transition instants and repeated-hour intervals
are calculated from the cited timezone rules; they are not independently
observed flight events or a default fold choice for the benchmark.

## View the recorded evidence

Render the committed November evidence as a static HTML report:

```bash
python examples/bts_validation_html.py \
  --input docs/evidence/bts-2025-11-route-cohort.json \
  --output bts-report-2025-11.html
```

Open `bts-report-2025-11.html` in a browser. It uses no JavaScript or remote fonts.
Archive/mapping hashes, period, runtime, dispositions, held-out comparison counts
and exclusions, source-input KPIs, normalizer findings and offset-window
diagnostics remain visible together. Choose a new output filename; existing
outputs are preserved. Rendering the JSON does not normalize new records or
validate another source file.

The [November HTML report](https://github.com/ubeydgencer/flightops-quality/releases/download/v0.2.4/bts-2025-11-report.html)
and [recorded JSON](https://github.com/ubeydgencer/flightops-quality/releases/download/v0.2.4/bts-2025-11-route-cohort.json)
are release assets. The machine-readable evidence is also retained in
[the November route-cohort JSON](evidence/bts-2025-11-route-cohort.json).

## Reproduction and timestamp policy

Run from the repository root after installing the package. Download the specified
BTS archive separately, then supply its local path. This external command uses
the official fixed source URL; the validator itself is offline:

```bash
curl --fail --location \
  'https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_11.zip' \
  --output bts-2025-11.zip
```

```bash
python -m pip install 'tzdata==2025.1'
PYTHONTZPATH='' python examples/validate_bts_month.py \
  --archive bts-2025-11.zip \
  --expected-sha256 6d5b68eea3ebb25f3cb2843e701a6c809b5455301b3bbd7802a20d522ed770c8 \
  --period 2025-11 \
  --source-url 'https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_11.zip' \
  --timezones examples/airport_timezones.json \
  --output bts-validation-2025-11
```

Choose a new output directory. `--source-url` records a provenance label; it does
not initiate a download. Preserve the archive and generated artifacts for
repeatable analysis.

The recorded v0.2.4 run used CPython **3.12.14** on macOS and
`tzdata==2025.1`, containing IANA **2025a**. Select the same Python environment
for replay. The [tzdata release notes](https://github.com/python/tzdata/blob/master/NEWS.md)
document the package-to-IANA release relationship.

Pin Python, tzdata and the mapping to reproduce the recorded analysis. Set
`PYTHONTZPATH=''` before starting Python so ZoneInfo uses the pinned package
instead of the system search path. Installing tzdata alone does not establish
which rules were used; the evidence records package/IANA versions and timezone
search paths.
The recorded `timezone_system_search_paths` list is empty.

A completed run writes `validation.json`, `validation.html` and `cohort.csv`
together. Exit 0 means that the complete evidence directory was written, even
when findings or held-out mismatches remain. Source/configuration errors exit 2
without publishing a partial directory. Bounds fail instead of truncating the
cohort.

The benchmark supplies neither a scheduled-midnight policy nor a departure-fold
choice. Scheduled `2400` therefore needs a verified date anchor. An ambiguous
scheduled local departure is an error rather than a guessed first or second
occurrence. Nonexistent local clocks also remain findings. Signed departure
delay and elapsed/taxi durations derive subsequent instants from a resolved
schedule anchor; an actual local clock alone does not invent a date or choose a
fold.

## Source-field reconstruction and KPI accounting

Original rows determine accepted, quarantined and exact-repeat dispositions as
one batch. A separate probe withholds `ArrDelay` and `AirTime` simultaneously,
reconstructs their metrics from the remaining schedule, signed departure delay,
elapsed and taxi evidence, then compares the results with the withheld source
fields.

Each held-out comparison accounts for every selected source row as a checked
record or an explicit exclusion. Checked records split into matches and
mismatches. Cancellations, diversions, missing/invalid targets, probe errors and
unresolved predictions are not silently counted as matches. An ambiguous anchor
that blocks reconstruction remains an exclusion even if reported target fields
are present.

Source-input KPI accounting reads reported signed `ArrDelay` for the selected
source cohort and the original batch's accepted unique population. Accepted-source
parity compares the latter population with the package summary. This checks
accounting and denominator policy; it is not independent reconstruction of a
field that participated in original-row validation.

Arrival OTP counts a delay **below 15 minutes** as on time; exactly 15 is late.
Arrival coverage divides eligible accepted normal flights by all accepted normal
flights, including those missing arrival delay. Quarantine rate uses accepted
plus quarantined records and excludes exact repeats. See
[quality gates](quality-gates.md) for full formulas and empty-population behavior.
Route-cohort OTP is not a national or airline-wide performance result.

## Observed results

The source scan covers **1–30 November 2025**, reads **570,550 source rows** and
selects **3,246** using only the two-airport membership predicate.

| Cohort accounting | Rows |
|---|---:|
| Selected source rows | 3,246 |
| Accepted unique rows | 3,245 |
| Quarantined rows | 1 |
| Exact repeats | 0 |
| Source cancelled flights | 87 |
| Source diverted flights | 6 |
| Source normal flights with reported arrival delay | 3,153 |
| Accepted normal flights with usable arrival delay | 3,152 |

| Selected route | Rows |
|---|---:|
| JFK → LAX | 862 |
| JFK → ORD | 176 |
| LAX → JFK | 860 |
| LAX → ORD | 584 |
| ORD → JFK | 176 |
| ORD → LAX | 588 |

The held-out checks account for **every selected source row**:

| Held-out source field | Compared | Matched | Mismatched | Cancelled | Diverted | Ambiguous schedule anchor |
|---|---:|---:|---:|---:|---:|---:|
| `ArrDelay` | 3,152 | 3,152 | 0 | 87 | 6 | 1 |
| `AirTime` | 3,152 | 3,152 | 0 | 87 | 6 | 1 |

For each field, `3,152 + 87 + 6 + 1 = 3,246`. There are no additional exclusion
reasons in the run. The zero-mismatch result
applies to **3,152 comparable normal rows**, not all 3,246 flights.

### An unresolved repeated-hour anchor

Source CSV line **234864** describes NK flight **1332**, LAX → ORD, with service
date **2 November 2025** and scheduled local departure `CRSDepTime=0120`.
In `America/Los_Angeles`, that local clock has two possible instants under the
pinned rules:

| Local departure | UTC candidate | Fold |
|---|---|---:|
| 2 November 01:20 −07:00 | 2 November 08:20 UTC | 0 |
| 2 November 01:20 −08:00 | 2 November 09:20 UTC | 1 |

The benchmark does not select either candidate. It supplies
`departure_fold=None`, so the row is quarantined with `TIME_AMBIGUOUS` and its
derived gate/runway timestamps remain null. The reported local clock is valid;
the finding records missing disambiguation under this policy, rather than
establishing that the provider reported an incorrect time.

The same row also has three `BTS_TIME_UNRESOLVED` field findings, plus
`SCHEDULE_INCOMPLETE` and `ACTUAL_INCOMPLETE` warnings. In the recorded evidence,
`validation.normalizer_issue_counts` counts source rows containing a code, so
each of the four codes has a count of one. By contrast,
`validation.batch_summary.issue_counts` counts every finding occurrence:
`BTS_TIME_UNRESOLVED` has three and the other codes have one each. These
**six occurrences affect one row**. The row is excluded from both held-out
comparisons with the explicit `dst_ambiguous` reason.

Its reported `ArrDelay=-12` is usable in source-input accounting and counts as
on time there. A reported target value does not resolve the schedule anchor or
turn an unresolved reconstruction into a held-out match.

The optional [warehouse findings report](guide-tr.md#veri-ambarındaki-bulguları-sayma)
shows both populations after the extracted cohort is audited and loaded into
SQLite. Among 3,246 raw records, one quarantined record has all six finding
occurrences; the 3,245 accepted records have none. Each code/severity group has
one affected record, including the group with three `BTS_TIME_UNRESOLVED`
occurrences. Group-level affected counts overlap and must not be added to obtain
the global affected population. The report reads recorded findings; it does not
add independent timestamp evidence or resolve the ambiguous departure.

### Metrics and denominators

| Arrival OTP population | Eligible | On time | Late | OTP |
|---|---:|---:|---:|---:|
| Selected source normal rows, using reported `ArrDelay` | 3,153 | 2,394 | 759 | 75.9277% |
| Accepted unique normal rows, using reported `ArrDelay` | 3,152 | 2,393 | 759 | 75.9201% |
| Package summary for accepted unique normal rows | 3,152 | 2,393 | 759 | 75.9201% |

All six accepted-source parity fields agree: eligible population, coverage
population, on-time count, late count, OTP and arrival coverage. The unresolved
row accounts for the difference between source and accepted populations. This
is denominator accounting; it does not attribute cancellation reasons or
explain performance differences between months.

Accepted arrival coverage is **100%** (`3,152 / 3,152`). Quarantine rate is
**0.03081%** (`1 / (3,245 + 1)`). These are observed data-quality and selected-route
metrics, with their recorded populations.

## Interpreting autumn offset coverage

Offset diagnostics use the original accepted unique population and already
resolved aware timestamps. Scheduled **SOBT → SIBT** windows include every
accepted status, including cancellation and diversion. Actual **AOBT → AIBT**
windows include accepted non-cancelled, non-diverted flights only. Quarantined
records and exact repeats are excluded from both populations; missing endpoints
have an explicit exclusion count.

Each distinct origin/destination IANA zone is compared **with itself at both UTC
endpoints**. Origin and destination offsets are not compared to each other.
A shared zone counts once. `offset_change_rows` counts windows with at least one
endpoint-offset difference; `zone_change_observations` counts changed zones
within those windows. The evidence retains up to ten changed-window examples
per population, rather than every changed window.

| Window | Population | Checked | Missing endpoints | Windows with an offset change | Changed-zone observations |
|---|---:|---:|---:|---:|---:|
| Scheduled, accepted unique all-status | 3,245 | 3,245 | 0 | 16 | 23 |
| Actual, accepted unique normal | 3,152 | 3,152 | 0 | 14 | 20 |

For example, source CSV line **80851**, service date **2 November 2025**,
LAX → ORD, has a resolved actual window from **07:28 UTC to 11:27 UTC** that day.
Converting both endpoints into `America/Los_Angeles` gives **00:28 −07:00** and
**03:27 −08:00**: a backward offset change of 60 minutes. This records one changed
flight window and one changed-zone observation. It describes the same two UTC
endpoints in that zone, rather than asserting the aircraft was in Los Angeles
at the arrival endpoint.

A backward offset change in a resolved window is different from an unresolved
repeated local departure hour. The former describes the pinned runtime's offset
path at two derived UTC instants; the latter requires source evidence to choose
an instant. A month containing an autumn transition does not itself show that
the cohort contains ambiguous scheduled departures or exercises both fold
choices.

These diagnostics do not independently prove absolute UTC dates, airport-zone
assignments or flight movements. Only endpoints are compared, so multiple
changes that cancel out within a window can be missed. In a general historical
dataset, an offset change is not necessarily a daylight-saving change.

## Limits of this evidence

This route cohort supplements the dated January/March evidence and synthetic
edge-case tests. It does not establish full-month/all-airport accuracy, a general
historical airport resolver or airline production readiness. The underlying
row ruleset remains **0.1.1**; benchmark diagnostics do not change record
acceptance rules or repair source fields by guessing.

Independent absolute UTC evidence, additional airports and periods, source
revisions and consumer feeds require separate validation. The package remains a
batch alpha with explicit uncertainty and caller-selected data-quality policy.

An additional review of the six timestamp roles in their applicable airport
zones finds one accepted repeated-hour instant: AA flight 999, source CSV line
**300642**, has derived **ATOT = 2 November 08:14 UTC**, or **01:14 −07:00** in
Los Angeles, the first occurrence (fold 0). It follows from AOBT at 07:58 UTC
plus `TaxiOut=16` minutes; AOBT itself is 00:58 local, outside the repeated hour.
There are no accepted fold-1 timestamps or repeated-hour origin AOBT values in
this cohort. This derived fold-0 runway instant, the unresolved scheduled anchor
and backward-offset windows do not establish coverage of both actual-departure
fold occurrences. The synthetic two-fold tests remain separate evidence.
