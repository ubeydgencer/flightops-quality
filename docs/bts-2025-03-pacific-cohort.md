# BTS Pacific route cohort — March 2025

Reviewed and executed **28 October 2026** with flightops-quality 0.2.8.
This adds **PHX (Phoenix) and HNL (Honolulu)** to the previously demonstrated
JFK/LAX/ORD scope. LAX connects the new airports and provides a DST-observing
contrast to their fixed offsets. Selection is every monthly row whose **Origin
and Dest both belong to `{HNL, LAX, PHX}`**, with all statuses retained. It does
not establish correctness for all BTS data or independent absolute UTC instants.

## Official sources and airport mapping

The [official BTS March 2025 archive](https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_3.zip)
and [field dictionary](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ)
identify the source and holdout meanings. The full monthly CSV is scanned and
hashed; source-row positions, airport IDs and date bounds remain in the evidence.

| Airport | FAA city / state / county | FAA site | IANA zone |
|---|---|---|---|
| HNL | Honolulu / HI / Honolulu | `52161.` | `Pacific/Honolulu` |
| LAX | Los Angeles / CA / Los Angeles | `01818.` | `America/Los_Angeles` |
| PHX | Phoenix / AZ / Maricopa | `00754.` | `America/Phoenix` |

The mapping is a project-curated inference from FAA locations and IANA zones,
not an official IATA-to-IANA lookup. Airport identity and coordinates were
reviewed in the FAA [20 February](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-02-20/)
and [20 March 2025](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-03-20/)
APT_BASE.csv snapshots spanning the reporting month. Bounded excerpts, download
URLs, hashes and the check date are in the [mapping review](evidence/bts-2025-03-pacific-mapping.json).
BTS and FAA identifiers use separate namespaces.

[IANA 2025a northamerica](https://data.iana.org/time-zones/tzdb-2025a/northamerica)
assigns Phoenix UTC−07:00 and Honolulu UTC−10:00 throughout this period. Los
Angeles advances from UTC−08:00 to UTC−07:00 on 9 March. These are rule-derived
expectations; source-field agreement is not independent timezone validation.
The replay uses pinned `tzdata==2025.1` (IANA 2025a), with `PYTHONTZPATH=''`
to bypass system rules. Full runtime metadata is retained in the JSON.

The recorded run used CPython **3.9.6** on macOS. Observed BTS AirportID /
AirportSeqID pairs were HNL `12173` / `1217305`, LAX `12892` / `1289208`,
and PHX `14107` / `1410702`.

## Recorded results

| Artifact | SHA-256 |
|---|---|
| Monthly ZIP | `9c80fbc2112cdbf3f0613ec2001ba019b3ad75511cd69657080736e7eda9cef4` |
| Source CSV | `ba031a484a67f743869bc1284a09fa1de61cf35a6da010e87674a3dc128590d0` |
| Timezone map | `7fcaa20c8956000f0945e76ded0ddc01cc19d170947b66c0a0dbd8da5cfcd24d` |
| Generated cohort CSV | `661cfb285b778881da15bcdc704a5918fc176b81d4589aabf8bd2f084e9cf15e` |

```json
{
  "input_rows": 2578,
  "group_dispositions": {
    "input": 2578,
    "accepted": 2578,
    "quarantined": 0,
    "duplicates": 0
  },
  "source_status_counts": {
    "Cancelled": {
      "0": 2576,
      "1": 2,
      "invalid": 0
    },
    "Diverted": {
      "0": 2576,
      "1": 2,
      "invalid": 0
    },
    "cohorts": {
      "normal": 2574,
      "cancelled_only": 2,
      "diverted_only": 2,
      "cancelled_and_diverted": 0,
      "invalid_status": 0
    }
  },
  "holdout_checks": {
    "ArrDelay": {
      "metric": "arrival_delay_minutes",
      "checked": 2574,
      "matched": 2574,
      "mismatched": 0,
      "excluded_counts": {
        "cancelled": 2,
        "diverted": 2
      },
      "mismatch_examples": [],
      "input_rows": 2578,
      "reconciled": true
    },
    "AirTime": {
      "metric": "airborne_minutes",
      "checked": 2574,
      "matched": 2574,
      "mismatched": 0,
      "excluded_counts": {
        "cancelled": 2,
        "diverted": 2
      },
      "mismatch_examples": [],
      "input_rows": 2578,
      "reconciled": true
    }
  }
}
```

All **600,872** monthly rows were scanned; **2,578** were selected and accepted
uniquely, with **zero quarantines and zero duplicates**. Both holdouts matched
all **2,574** comparable rows, excluding two cancellations and two diversions
each. Four scheduled and four actual HNL–LAX windows cross the Los Angeles
offset transition; Phoenix and Honolulu contribute no offset-change observations.
No ambiguous/gap finding occurred in this cohort, so it adds no real fold/gap
coverage claim.

The holdout probe withholds both ArrDelay and AirTime before reconstructing
those fields from the remaining inputs. Each target partitions all selected
rows into compared or explicitly excluded populations. Source-input KPI parity
is separate and does not count as an independent holdout. Cancellation,
diversion, duplicate and quarantine dispositions remain visible even when zero.
No scheduled-midnight date or DST fold is guessed. The evidence records findings
and unresolved instants rather than filtering them away. No synthetic rows are
added to make rare cases appear covered.

## Reproduce and view

From a checkout, create an isolated environment and install the project and
pinned timezone data. Download the official archive separately:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e . 'tzdata==2025.1'
curl --fail --location \
  'https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_3.zip' \
  --output bts-2025-03.zip
PYTHONTZPATH='' .venv/bin/python examples/validate_bts_month.py \
  --archive bts-2025-03.zip \
  --expected-sha256 9c80fbc2112cdbf3f0613ec2001ba019b3ad75511cd69657080736e7eda9cef4 \
  --period 2025-03 \
  --source-url 'https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_3.zip' \
  --timezones examples/airport_timezones_pacific.json \
  --output bts-validation-2025-03-pacific
```

Choose a new output directory: existing outputs are preserved. The validator is
offline and the source URL is only a provenance label. A successful exit means
evidence was written; it does not certify absence of findings. The existing
archive/CSV/row/column/cohort limits apply; exceeded limits fail rather than
truncating the selection.

The generated directory contains `cohort.csv`, `validation.json` and
`validation.html`. Archive and full cohort are deliberately not committed.
The [bounded JSON evidence](evidence/bts-2025-03-pacific-cohort.json) and
[static HTML report](evidence/bts-2025-03-pacific-report.html) are committed.
Download the HTML and open locally; it has no JavaScript or remote resources.
Regenerate it without the raw dataset:

```sh
.venv/bin/python examples/bts_validation_html.py \
  --input docs/evidence/bts-2025-03-pacific-cohort.json \
  --output bts-report-2025-03-pacific.html
```

The JSON schema is shared with the existing dated cohorts. Replay can change
runtime metadata across Python/platform versions; source, mapping and cohort
hashes plus validation results are the reproducibility checks.
