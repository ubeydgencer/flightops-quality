# BTS Reporting Carrier route-cohort validation — January 2025

This benchmark evaluates a dated route cohort from one real BTS monthly source.
It selects every source row whose origin and destination are both in
`{JFK, LAX, ORD}`. It does not validate the complete monthly dataset, all airports,
other reporting periods or an airline production feed. The bundled example CSVs
remain synthetic; the original BTS archive is downloaded separately.

## Source artifact and extraction

The source is the [January 2025 Reporting Carrier On-Time Performance archive](https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_1.zip)
published by the US Bureau of Transportation Statistics. The
[BTS field dictionary](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ)
defines the local clocks, signed delays, elapsed/taxi times and status fields used
by the adapter.

| Artifact | Size | SHA-256 |
|---|---:|---|
| Monthly ZIP | 27,108,664 bytes | `868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf` |
| Source CSV inside the ZIP | 243,177,378 bytes | `d7c7d59452cad1215d9605e8ff350a4bad7282750765084fe57928a5ad275453` |

The offline validator requires the expected ZIP digest, applies ZIP/CSV size
bounds, checks source dates against the requested month and records the archive,
source CSV and mapping hashes. It reads the CSV without extracting arbitrary
archive paths. A digest identifies the exact downloaded artifact; it is not a
signature from BTS or proof that BTS will never revise the source.

The recipe caps compressed input at 64 MiB, the decompressed CSV at 512 MiB,
source rows at 1,000,000 and columns at 256. The selected cohort is limited to
20,000 rows, 2,000,000 cells and 64 MiB of UTF-8 field values. A limit failure
stops the run rather than publishing a truncated cohort.

## Cohort definition

The filter is `Origin in map.keys() and Dest in map.keys()` over the entire
monthly source. There is no cancellation, diversion, delay or completeness
filter. All 110 source columns, including the empty trailing header, are retained
in `cohort.csv`, with
`_source_line_number` added to preserve the original CSV position. The extracted
cohort is generated locally and is not committed to the repository. The versioned
JSON evidence includes a bounded diagnostic source excerpt; the original monthly
archive and full extracted cohort are not bundled.

The cohort is analyzed as one batch so exact repeats and identity conflicts are
resolved across all selected rows. Source-wide scan counts and selected-cohort
counts are separate measurements. A route-cohort result must not be presented as
the monthly national totals.

## Airport identity and timezone provenance

The supplied map is a project-curated inference from FAA airport locations and
IANA zone definitions. Neither source provides a direct official IATA-to-IANA
airport mapping.

| Source code | FAA city / state / county | FAA site number | IANA zone |
|---|---|---|---|
| JFK | New York / NY / Queens | `15793.` | `America/New_York` |
| LAX | Los Angeles / CA / Los Angeles | `01818.` | `America/Los_Angeles` |
| ORD | Chicago / IL / Cook | `04508.` | `America/Chicago` |

The airport names, FAA identifiers, cities, states, counties and coordinates were
checked in both [26 December 2024 NASR](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2024-12-26/)
and [23 January 2025 NASR](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-01-23/)
`APT_BASE.csv` snapshots; those fields agree for all three airports. These dated
snapshots cover the cycles applicable during January. FAA site numbers are a
separate namespace and are not substituted for BTS airport IDs.

The [IANA 2025a zone catalog](https://data.iana.org/time-zones/tzdb-2025a/zone1970.tab)
defines the New York, Chicago and Los Angeles zones. Its
[North America rules](https://data.iana.org/time-zones/tzdb-2025a/northamerica)
provide the corresponding historical offsets and daylight-saving transitions.
These are the primary sources used to review the map; the runtime timezone
database is recorded separately because source provenance and execution
environment are different inputs.

The original `OriginAirportID`, `DestAirportID`, airport sequence IDs,
`FlightDate`, city/state and carrier identifiers remain in the raw rows. BTS
recommends AirportID for analysis over years because codes can change or be
reused; AirportSeqID identifies an airport's attributes at a particular point in
time. See [the BTS definitions](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ).
This three-entry review does not establish a general historical airport catalog.

| Reviewed primary artifact | SHA-256 |
|---|---|
| [FAA 26 December 2024 APT ZIP](https://nfdc.faa.gov/webContent/28DaySub/extra/26_Dec_2024_APT_CSV.zip) | `40524f2728225a1bcf72bc297962f32a3e24d3b13fededb7f197584c2cda18fd` |
| [FAA 23 January 2025 APT ZIP](https://nfdc.faa.gov/webContent/28DaySub/extra/23_Jan_2025_APT_CSV.zip) | `009b04926e187628fd1560eb8b6925012f0a1aeb855a9c9653eff61fddac9df0` |
| IANA 2025a `northamerica` | `bb441456077da404a1997a50abfee95ac11937d9c28278cfe36f85277227c1f1` |

## View the recorded evidence

Render the committed JSON evidence as a static HTML report:

```bash
python examples/bts_validation_html.py \
  --input docs/evidence/bts-2025-01-route-cohort.json \
  --output bts-report.html
```

Open `bts-report.html` in a browser. The report works offline, uses no JavaScript
or remote fonts, and shows the archive/mapping hashes, source period and recorded
environment alongside dispositions, held-out comparisons and their exclusion
populations. It includes the original clock findings and keeps source-input OTP
separate from accepted-cohort OTP. The source JSON remains the machine-readable
evidence; rendering it does not rerun normalization or validate a new dataset.

Choose a new output filename. The renderer publishes the complete HTML privately
and atomically, refuses to overwrite an existing destination, and reports invalid
input or output errors clearly.

## Reproduction

Run from the repository root after installing the package. Download the specified
BTS archive separately, then supply its local path. The validator itself is
offline and does not fetch source data. This external download command uses the
official fixed archive URL:

```bash
curl --fail --location \
  'https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_1.zip' \
  --output bts-2025-01.zip
```

```bash
python -m pip install 'tzdata==2025.1'
PYTHONTZPATH='' python examples/validate_bts_month.py \
  --archive bts-2025-01.zip \
  --expected-sha256 868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf \
  --period 2025-01 \
  --source-url 'https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_1.zip' \
  --timezones examples/airport_timezones.json \
  --output bts-validation-2025-01
```

Choose a new output directory. The result contains `validation.json`,
`validation.html` and `cohort.csv`. Keep those artifacts together with the original
archive and runtime environment for repeatable analysis. The versioned aggregate evidence
is retained in [the January route-cohort JSON](evidence/bts-2025-01-route-cohort.json).
`--source-url` records a provenance label; it does not initiate a download.

The recorded v0.2.1 benchmark used CPython **3.12.14** on macOS and
`tzdata==2025.1`, which contains IANA **2025a**. Select the same Python environment
for replay.
The [tzdata release notes](https://github.com/python/tzdata/blob/master/NEWS.md)
document that package-to-IANA release relationship.
`PYTHONTZPATH=''` makes the system search path empty so ZoneInfo uses the pinned
package. The evidence records an empty `timezone_system_search_paths` list;
installing tzdata without changing the search path would not itself prove that
the package supplied the runtime rules.

Exit 0 means the complete evidence directory was written; findings and
hold-out mismatches remain visible inside the report. It does not mean every
record was accepted. Source/configuration errors exit 2 without publishing a
partial directory. The bounds are listed in the JSON; exceeded limits fail
instead of truncating a sample.

No midnight anchor or DST fold is guessed in this benchmark. Scheduled `2400`
without a verified date policy remains unresolved; ambiguous local departure
times require source evidence. This differs from the deliberately configured
`end` policy in the synthetic BTS quickstart.

## Source-field cross-checks

There are two distinct kinds of comparison:

- **Source-input KPI parity** compares metrics/populations against the reported
  BTS fields for the same selected cohort. It checks accounting and denominator
  policy. Because those source fields can also participate in adapter
  validation, agreement alone is not independent validation of their derivation.
- **Held-out reconstruction** removes `ArrDelay` and `AirTime` from the row passed
  to the probe normalizer. The probe reconstructs arrival delay and airborne time
  from the remaining schedule, signed departure delay, elapsed and taxi evidence,
  then compares the resulting values with the original held-out source fields.
  The held-out values are used only after normalization, rather than as inputs to
  that probe's reconstruction or source-value checks.

The held-out comparison is independent of those two target fields, while still
depending on other fields reported by the same provider. It is not external
ground truth for actual flight movements, and does not independently verify
absolute UTC dates or timezone assignments. Cancellation, diversion, missing
targets and unresolved reconstructions have explicit comparison populations;
they must not be silently counted as matches or discarded from the evidence.

## Observed results

The recorded source scan covers **1–31 January 2025**. It finds **539,747 source
rows** and selects **2,929** rows using only the two-airport membership predicate.

| Cohort accounting | Rows |
|---|---:|
| Selected source rows | 2,929 |
| Accepted unique rows | 2,928 |
| Quarantined rows | 1 |
| Exact repeats | 0 |
| Source cancelled flights | 11 |
| Source diverted flights | 8 |
| Accepted normal flights with usable arrival delay | 2,909 |

The held-out checks account for **every selected source row**:

| Held-out source field | Compared | Matched | Mismatched | Cancelled | Diverted | Probe clock mismatch |
|---|---:|---:|---:|---:|---:|---:|
| `ArrDelay` | 2,909 | 2,909 | 0 | 11 | 8 | 1 |
| `AirTime` | 2,909 | 2,909 | 0 | 11 | 8 | 1 |

For each field, `2,909 + 11 + 8 + 1 = 2,929`. There are no additional missing or
unresolved exclusions in this observed cohort. The zero-mismatch result is over
the **2,909 comparable rows**, rather than every input flight.

### A clock-consistency finding

Source CSV line **441440** describes DL flight 960, LAX → JFK, with service date
**10 January 2025**. The reported scheduled departure is `2110` and scheduled
elapsed time is 317 minutes. Actual departure is `2248` and actual elapsed time
is 361 minutes. Under the reviewed timezone map and duration-derived dates:

| Source clock | Reported HHMM | Derived local clock on 11 January, New York |
|---|---|---|
| `CRSArrTime` | `0525` | `05:27` |
| `ArrTime` | `0747` | `07:49` |
| `WheelsOn` | `0740` | `07:42` after subtracting `TaxiIn=7` |

All three derived clocks are two minutes later than their source clocks. The
original row is quarantined with `BTS_CLOCK_MISMATCH`; issue counts count rows
containing a code, so this is **one affected row with three field findings**.

The delay/duration algebra can still reproduce reported `ArrDelay=142` and
`AirTime=277`. The separate probe also finds the clock discrepancies, so this row
is excluded from both held-out comparisons rather than counted as a match.
This records a contradiction under the adapter's documented assumptions; it does
not identify which reported field is wrong or repair the source by guessing.

## Metrics and denominators

Arrival OTP uses accepted unique, non-cancelled, non-diverted flights with usable
arrival delay. A delay below 15 minutes is on time; exactly 15 minutes is late.
Arrival coverage divides that eligible population by all accepted normal flights,
including those missing arrival delay. Quarantine rate divides quarantined rows
by accepted plus quarantined rows, excluding exact repeats.

The source cohort, accepted cohort and held-out comparable populations answer
different questions. Report their counts and exclusions beside the percentages.
These calculations follow the project's documented quality-cohort policy, not a
claim to reproduce every BTS published national KPI. See
[quality gates](quality-gates.md) for full formulas and nullable denominators.

| Arrival OTP population | Eligible | On time | Late | OTP |
|---|---:|---:|---:|---:|
| Selected source normal rows, using reported `ArrDelay` | 2,910 | 2,510 | 400 | 86.2543% |
| Accepted unique normal rows | 2,909 | 2,510 | 399 | 86.2839% |

The quarantined row has a reported arrival delay of 142 minutes, so it is late
in the source-input calculation and excluded from the accepted KPI population.
Accepted-source KPI parity compares reported delay values for those same accepted
unique rows with the package summary; it does not compare the accepted cohort
against a different source-wide denominator.

Accepted arrival coverage is **100%** (`2,909 / 2,909`). Quarantine rate is
**0.03414%** (`1 / (2,928 + 1)`). These are observed data-quality and route-cohort
metrics; they are not national or airline-wide performance results.

## Limits of this evidence

January does not exercise the US spring or autumn DST transitions. Other
airports, historical code changes, source revisions, schedule-midnight conventions
and production feeds require separate validation. Synthetic tests continue to
cover deliberately constructed edge cases; real-source agreement supplements
those tests rather than replacing them.

This benchmark establishes observed behavior on one dated route cohort. It does
not establish full-month/all-airport accuracy, flight-safety certification,
airline affiliation or deployment readiness. The core remains a batch API with
explicit uncertainty and consumer-selected data-quality policy.
