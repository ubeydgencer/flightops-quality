import unittest

from flightops_quality.adapters.canonical import normalize_record


def valid_row():
    return dict(source="demo", record_id="1", service_date="2026-10-09", carrier="ZZ",
                flight_number="100", origin="IST", destination="FRA",
                sobt="2026-10-09T09:00:00+03:00", sibt="2026-10-09T11:00:00+02:00",
                aobt="2026-10-09T08:55:00+03:00", aibt="2026-10-09T11:14:00+02:00")


class CanonicalTests(unittest.TestCase):
    def test_aware_normalization_preserves_raw_and_provenance(self):
        row = valid_row()
        result = normalize_record(row, row_number=42)
        self.assertTrue(result.accepted)
        self.assertEqual(result.flight.sobt.hour, 6)
        self.assertEqual(result.flight.provenance["sobt"], ("sobt",))
        self.assertEqual(result.raw, row)
        self.assertEqual(result.row_number, 42)

    def test_fold_requires_explicit_resolution(self):
        row = {**valid_row(), "sobt": "2026-11-01T01:30:00", "sibt": "2026-11-01T10:00:00Z",
               "aobt": "", "aibt": "", "origin_timezone": "America/New_York"}
        unresolved = normalize_record(row)
        self.assertFalse(unresolved.accepted)
        issue = next(i for i in unresolved.issues if i.code == "TIME_AMBIGUOUS")
        self.assertEqual(issue.fields, ("sobt",))
        resolved = normalize_record({**row, "sobt_fold": "1"})
        self.assertTrue(resolved.accepted)
        self.assertEqual(resolved.flight.sobt.hour, 6)
        self.assertEqual(resolved.flight.provenance["sobt"], ("sobt", "origin_timezone", "sobt_fold"))

    def test_invalid_identity_date_flag(self):
        for field, value in [("source", ""), ("service_date", "20261009"),
                             ("service_date", "2026-02-30"), ("cancelled", "maybe"),
                             ("flight_number", 100), ("aircraft_registration", [])]:
            with self.subTest(field=field):
                result = normalize_record({**valid_row(), field: value})
                self.assertFalse(result.accepted)
                self.assertTrue(any(field in i.fields for i in result.issues))

    def test_non_json_raw_contract_fails_clearly(self):
        for value in (float("nan"), object()):
            with self.assertRaisesRegex(ValueError, "JSON-compatible"):
                normalize_record({**valid_row(), "extra": value})


if __name__ == "__main__":
    unittest.main()
