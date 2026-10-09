# Sources, related work and limits

Research checked on 9 October 2026. Rules are an independent interpretation for
data quality, not operational certification.

## Primary domain sources

- [BTS Reporting Carrier field dictionary](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ):
  signed departure delay, elapsed/taxi times, cancellation and diversion fields.
- [BTS 2026 Technical Directive #40](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-40-technical-directive-reporting-time):
  local HHMM clocks, midnight `2400`, and cancellation after gate return. A
  cancelled flight can legitimately report actual gate departure.
- [BTS 2025 Technical Directive #39](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time):
  reporting definitions for the January 2025 real-source route cohort.
- [EUROCONTROL A-CDM specification, 2025](https://www.eurocontrol.int/publication/eurocontrol-specification-airport-collaborative-decision-making-cdm):
  vocabulary distinguishing gate/block, runway, actual and target times. This
  package does not implement the full A-CDM specification or claim compliance.
- [Python ZoneInfo](https://docs.python.org/3/library/zoneinfo.html):
  IANA timezone support, fold handling and system/tzdata fallback.

The BTS adapter handles a bounded subset of Reporting Carrier fields. It does
not reconstruct diversion legs, gate-return history or every reporting rule.
BTS covers US reporting data.
The directive establishes `2400` as midnight. This alpha requires callers to
verify whether a scheduled midnight anchors the start or end of `FlightDate`
for their release, rather than claiming that either date policy was validated.

## Data and licensing

Bundled CSV fixtures were written for this project and contain no real flight records.
The [January 2025 route-cohort evidence](bts-2025-01-route-cohort.md) records a
separate real-source validation, with aggregate results and one bounded source
excerpt explaining a quarantined row. The full monthly source and extracted
cohort are downloaded/generated locally and are not bundled.
The [data.gov BTS Flight Data metadata](https://catalog.data.gov/dataset/bts-flight-data)
points to [US government works](https://www.usa.gov/government-works); it does not
label the dataset CC0. Users should check the actual source file and terms,
including third-party content. This repository does not relicense external data.

OpenSky is outside the current adapter scope: its trajectory observations are not a
schedule/delay/cancellation source, and operational use has separate terms.
See its [FAQ](https://opensky-network.org/about/faq) and
[terms](https://opensky-network.org/about/terms-of-use).

## Related open-source work

- [airportsdata](https://github.com/mborsetti/airportsdata): airport code and timezone lookups.
- [traffic](https://traffic-viz.github.io/): trajectory and airspace analysis.
- [ROSTER](https://github.com/JBlank19/roster): historical data normalization and synthetic schedules.
- [BFD](https://github.com/cefet-rj-dal/bfd): aviation/weather ETL and quality flags.
- [AeroEmbed](https://github.com/SynthAIr/AeroEmbed): flight preprocessing and representations.
- [Pandera](https://pandera.readthedocs.io/en/stable/index.html): general dataframe validation.

The field is populated. This package explores a narrower reusable interface:
standard-informed operational timestamps, explicit uncertainty and derivation
provenance, whole-group conflict quarantine and explainable metric populations.
Its usefulness and demand still need user validation.
