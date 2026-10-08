# Contributing

Please open an issue with a minimal synthetic row, expected finding/metric and
the provider documentation supporting the behavior. Do not attach passenger
data, private airline feeds, secrets or proprietary airport connection tables.

For changes, run the commands in README's Development section. Add a regression
test that demonstrates the domain failure, preserve row accounting, and document
new rule codes in `docs/rules.md`. Formatting-only changes do not need tests.
Generated reports and local databases should stay outside version control.

New adapters should explain their identity, timezone, null and cancellation
policies. Keep runtime dependencies optional where practical. Do not describe
standards-inspired checks as certified compliance.
