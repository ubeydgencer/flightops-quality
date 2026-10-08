# Rule catalog — 0.1.0

Errors quarantine a row. Warnings retain an incomplete observation without
inventing its missing values. Info findings audit exact repeats. Adapter findings
refer to raw source fields; canonical rules refer to normalized timestamp names.

| Code | Severity | Meaning / resolution |
|---|---|---|
| `FIELD_REQUIRED` | error | Required identity field absent, empty or wrong type. Supply source-supported identity. |
| `FIELD_INVALID` | error | Invalid optional/scalar field type. Correct the source value. |
| `DATE_INVALID` | error | Service date is not a valid `YYYY-MM-DD`. |
| `FLAG_INVALID` | error | Status flag outside the adapter's documented boolean / 0/1 contract. |
| `TIME_INVALID` | error | Invalid ISO datetime, clock, offset, type or UTC range. |
| `TIME_FOLD_INVALID` | error | Fold must be integer 0 or 1. |
| `TIME_ZONE_REQUIRED` | error | Naive ISO datetime needs an explicit IANA timezone. |
| `TIME_ZONE_UNKNOWN` | error | Unknown zone, unavailable database or missing BTS airport mapping. |
| `TIME_AMBIGUOUS` | error | Local clock occurs twice. Supply an authoritative offset or explicit fold. |
| `TIME_NONEXISTENT` | error | Local clock falls in a DST gap; repair it using source evidence. |
| `TIME_NOT_AWARE` | error | Direct `FlightLeg` timestamp does not identify a representable UTC instant. |
| `SCHEDULE_ORDER` | error | Scheduled gate arrival is not after scheduled gate departure. |
| `ACTUAL_ORDER` | error | Present actual gate/runway milestones have reversed chronology. |
| `SCHEDULE_INCOMPLETE` | warning | Scheduled gate time missing; affected delays remain null. |
| `ACTUAL_INCOMPLETE` | warning | Normal non-cancelled/non-diverted actual gate time missing. |
| `BTS_CLOCK_INVALID` | error | HHMM invalid; only 0000..2359 and 2400 are accepted. |
| `BTS_NUMBER_INVALID` | error | Minutes must be bounded finite integers; only delay fields may be negative. |
| `BTS_TIME_RANGE` | error | Date/duration derivation exceeds Python datetime's supported range. |
| `BTS_MIDNIGHT_UNRESOLVED` | error | Scheduled 2400 requires a caller-verified start/end-of-service-date policy. |
| `BTS_CLOCK_MISMATCH` | error | Duration-derived instant disagrees with reported local clock. |
| `BTS_DURATION_MISMATCH` | error | Derived arrival delay or airborne minutes disagree with source values. |
| `BTS_TIME_UNRESOLVED` | warning | Insufficient date/delay/elapsed evidence to resolve a local clock. |
| `DUPLICATE_EXACT` | info | Repeated raw payload under the same identity, audited separately. |
| `DUPLICATE_CONFLICT` | error | Conflicting raw payloads under one identity; all group members quarantined. |

The numeric parser rejects absolute values above 10^10 as a defensive parse
bound, not an aviation plausibility threshold. No universal maximum flight,
taxi or turnaround duration is imposed. Such thresholds need consumer context.

Canonical `source + record_id` comes from the caller. The default BTS identity
is a JSON tuple of flight date, operating/reporting carrier ID (fallback code),
flight number, origin/destination airport IDs (fallback codes), and raw scheduled
departure clock. It is an adapter policy, not a universal flight identifier.
An explicit `record_id` overrides it. Identity decisions and raw encodings should
be consistent across one batch; normalization context is not a revision resolver.
