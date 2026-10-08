import unittest
from datetime import datetime, timezone

from flightops_quality.time import resolve_timestamp


class TimeTests(unittest.TestCase):
    def test_dst_fold_is_not_guessed(self):
        value = "2026-11-01T01:30:00"
        unresolved = resolve_timestamp(value, "America/New_York")
        self.assertIsNone(unresolved.value)
        self.assertEqual(unresolved.issues[0].code, "TIME_AMBIGUOUS")
        first = resolve_timestamp(value, "America/New_York", fold=0).value
        second = resolve_timestamp(value, "America/New_York", fold=1).value
        self.assertEqual((second - first).total_seconds(), 3600)
        self.assertEqual(first.hour, 5)
        self.assertEqual(second.hour, 6)

    def test_dst_gap_is_not_shifted(self):
        result = resolve_timestamp("2026-03-08T02:30:00", "America/New_York")
        self.assertEqual(result.issues[0].code, "TIME_NONEXISTENT")
        self.assertIsNone(result.value)

    def test_aware_offset_overrides_lookup(self):
        result = resolve_timestamp("2026-11-01T01:30:00-05:00", "not-a-zone")
        self.assertEqual(result.value, datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc))
        self.assertFalse(result.issues)

    def test_unique_local_and_z(self):
        local = resolve_timestamp("2026-10-09T09:00:00", "Europe/Istanbul")
        self.assertEqual(local.value, resolve_timestamp("2026-10-09T06:00:00Z").value)

    def test_bad_input(self):
        for value, zone, code in [("2026-10-09", None, "TIME_INVALID"),
                                  ("2026-10-09T25:00", None, "TIME_INVALID"),
                                  ("2026-10-09T09:00", None, "TIME_ZONE_REQUIRED"),
                                  ("2026-10-09T09:00", "unknown", "TIME_ZONE_UNKNOWN"),
                                  (123, None, "TIME_INVALID")]:
            with self.subTest(value=value):
                self.assertEqual(resolve_timestamp(value, zone).issues[0].code, code)
        self.assertEqual(resolve_timestamp("2026-10-09T09:00", "UTC", 2).issues[0].code, "TIME_FOLD_INVALID")
        self.assertEqual(resolve_timestamp("2026-10-09T09:00", "UTC", 1.0).issues[0].code, "TIME_FOLD_INVALID")


if __name__ == "__main__":
    unittest.main()
