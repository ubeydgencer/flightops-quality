# Changelog

## 0.2.0 — 2026-10-09

- Arrival-delay coverage is reported separately from arrival OTP, with explicit
  observed and missing populations in Python and the independent route SQL.
- Opt-in batch quality gates validate minimum coverage, minimum OTP-eligible
  flight counts and maximum quarantine rates. Reports retain thresholds,
  measurements and reasons; a failed CLI gate writes the audit and exits 1.
- Accepted batch records must have a normalized flight with no error findings.
- Audit outputs and SQLite warehouses are published only after all writes and
  queries succeed. Existing outputs are preserved, including collision cases.
- SQLite enforces the quality-gate result by default and records an explicit
  failed-gate override. Internal record IDs preserve lineage when source row
  numbers repeat; flight metadata and audit versions remain available in SQL.
- The Turkish documentation is now a usage guide covering installation, data
  formats, quality checks, report interpretation and ETL integration.

## 0.1.1 — 2026-10-09

- Strict ISO offset bounds and canonical numeric BTS identities prevent silent
  timestamp changes and double-counting equivalent CSV encodings.
- Bounded CSV bytes, records, columns and cells; bounded timezone JSON with
  duplicate-key rejection and strict parsing.
- Validated deep raw snapshots prevent nested-key, surrogate Unicode, cyclic
  data and mutation-related audit failures.
- Extreme Decimal exponents become row findings. Blank CSV lines retain correct
  source line numbers. Every HTML source value, including row numbers, is escaped.
- Modern README/banner, security policy and private vulnerability reporting.

## 0.1.0 — 2026-10-09

First alpha: canonical and BTS batch adapters, UTC/DST validation, separate gate
and runway metrics, explainable audit reports, whole-group duplicate conflict
quarantine, synthetic examples and a local SQL warehouse demonstration.
