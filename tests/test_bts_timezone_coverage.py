import copy
import importlib.util
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.batch import analyze_results

ROOT = Path(__file__).resolve().parents[1]
ZONES = {"JFK": "America/New_York", "BOS": "America/New_York", "LAX": "America/Los_Angeles"}


def flight_row(record_id="spring", **changes):
    row = {
        "source": "timezone-test", "record_id": record_id, "service_date": "2025-03-09",
        "carrier": "ZZ", "flight_number": "100", "origin": "JFK", "destination": "BOS",
        "sobt": "2025-03-09T06:30:00+00:00", "sibt": "2025-03-09T07:30:00+00:00",
        "aobt": "2025-03-09T06:30:00+00:00", "aibt": "2025-03-09T07:30:00+00:00",
    }
    row.update(changes)
    return row


class BtsTimezoneCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "bts_timezone_coverage_tested", ROOT / "examples/bts_timezone_coverage.py"
        )
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def report(self, rows):
        return analyze_results(normalize_record(row, row_number=number)
                               for number, row in enumerate(rows, start=42))

    def coverage(self, rows, zones=None):
        return self.helper.timezone_offset_coverage(self.report(rows), ZONES if zones is None else zones)

    def assert_reconciled(self, document):
        for label in ("scheduled", "actual"):
            item = document[label]
            self.assertEqual(item["checked"] + sum(item["excluded_counts"].values()), item["population_rows"])
            self.assertTrue(item["reconciled"])

    def test_spring_forward_compares_one_zone_with_its_own_endpoints(self):
        result = self.coverage([flight_row()])
        for label in ("scheduled", "actual"):
            item = result[label]
            self.assertEqual((item["population_rows"], item["checked"], item["offset_change_rows"],
                              item["zone_change_observations"]), (1, 1, 1, 1))
            example = item["examples"][0]
            self.assertEqual(example["source_row_number"], 42)
            self.assertEqual(example["record_id"], "spring")
            self.assertEqual(example["service_date"], "2025-03-09")
            self.assertEqual((example["origin"], example["destination"], example["route"]), ("JFK", "BOS", "JFK-BOS"))
            self.assertEqual(example["window_start_utc"], "2025-03-09T06:30:00+00:00")
            self.assertEqual(example["window_end_utc"], "2025-03-09T07:30:00+00:00")
            self.assertEqual(example["changes"], [{
                "timezone": "America/New_York", "offset_start_seconds": -18000,
                "offset_end_seconds": -14400, "change_seconds": 3600,
                "local_start": "2025-03-09T01:30:00-05:00", "local_end": "2025-03-09T03:30:00-04:00",
            }])
        self.assert_reconciled(result)

    def test_fall_back_detects_offset_change_despite_identical_local_clocks(self):
        result = self.coverage([flight_row("fall", service_date="2025-11-02",
                                        sobt="2025-11-02T05:30:00Z", sibt="2025-11-02T06:30:00Z",
                                        aobt="2025-11-02T05:30:00Z", aibt="2025-11-02T06:30:00Z")])
        change = result["actual"]["examples"][0]["changes"][0]
        self.assertEqual((change["offset_start_seconds"], change["offset_end_seconds"], change["change_seconds"]),
                         (-14400, -18000, -3600))
        self.assertEqual(change["local_start"], "2025-11-02T01:30:00-04:00")
        self.assertEqual(change["local_end"], "2025-11-02T01:30:00-05:00")
        self.assert_reconciled(result)

    def test_different_airport_offsets_do_not_create_a_false_positive(self):
        result = self.coverage([flight_row("static", service_date="2025-03-10", destination="LAX",
                                        sobt="2025-03-10T12:00:00Z", sibt="2025-03-10T18:00:00Z",
                                        aobt="2025-03-10T12:00:00Z", aibt="2025-03-10T18:00:00Z")])
        for label in ("scheduled", "actual"):
            self.assertEqual(result[label]["checked"], 1)
            self.assertEqual(result[label]["offset_change_rows"], 0)
            self.assertEqual(result[label]["zone_change_observations"], 0)
            self.assertEqual(result[label]["examples"], [])

    def test_two_zones_changing_count_two_observations_but_one_window(self):
        result = self.coverage([flight_row("two-zones", destination="LAX",
                                        sibt="2025-03-09T10:30:00Z", aibt="2025-03-09T10:30:00Z")])
        for label in ("scheduled", "actual"):
            self.assertEqual(result[label]["offset_change_rows"], 1)
            self.assertEqual(result[label]["zone_change_observations"], 2)
            changes = result[label]["examples"][0]["changes"]
            self.assertEqual([change["timezone"] for change in changes], ["America/Los_Angeles", "America/New_York"])
            self.assertEqual([change["change_seconds"] for change in changes], [3600, 3600])

    def test_cancelled_and_diverted_keep_planned_windows_without_actual_population(self):
        result = self.coverage([flight_row("normal"), flight_row("cancelled", cancelled=True),
                                flight_row("diverted", diverted=True)])
        self.assertEqual(result["scheduled"]["population_rows"], 3)
        self.assertEqual(result["scheduled"]["checked"], 3)
        self.assertEqual(result["scheduled"]["offset_change_rows"], 3)
        self.assertEqual(result["actual"]["population_rows"], 1)
        self.assertEqual(result["actual"]["checked"], 1)
        self.assertEqual(result["actual"]["excluded_counts"], {"missing_timestamps": 0})
        self.assertEqual([example["record_id"] for example in result["actual"]["examples"]], ["normal"])
        self.assert_reconciled(result)

    def test_missing_each_endpoint_and_both_endpoints_count_one_exclusion_per_window(self):
        result = self.coverage([
            flight_row("complete"), flight_row("missing-start", sobt=None, aobt=None),
            flight_row("missing-end", sibt=None, aibt=None),
            flight_row("missing-both", sobt=None, sibt=None, aobt=None, aibt=None),
        ])
        for label in ("scheduled", "actual"):
            self.assertEqual(result[label]["population_rows"], 4)
            self.assertEqual(result[label]["checked"], 1)
            self.assertEqual(result[label]["excluded_counts"], {"missing_timestamps": 3})
            self.assertEqual(result[label]["offset_change_rows"], 1)
        self.assert_reconciled(result)

    def test_duplicate_and_quarantined_rows_are_excluded_from_population(self):
        repeated = flight_row()
        conflict = flight_row("conflict")
        rows = [repeated, dict(repeated), conflict, {**conflict, "unresolved_revision": "different"},
                flight_row("naive", sobt="2025-03-09T01:30:00")]
        report = self.report(rows)
        self.assertEqual(report.counts, {"input": 5, "accepted": 1, "quarantined": 3, "duplicates": 1})
        result = self.helper.timezone_offset_coverage(report, ZONES)
        for label in ("scheduled", "actual"):
            self.assertEqual(result[label]["population_rows"], 1)
            self.assertEqual(result[label]["checked"], 1)
            self.assertEqual([example["record_id"] for example in result[label]["examples"]], ["spring"])

    def test_examples_are_bounded_without_truncating_counts(self):
        result = self.coverage([flight_row(str(number)) for number in range(12)])
        for label in ("scheduled", "actual"):
            self.assertEqual(result[label]["checked"], 12)
            self.assertEqual(result[label]["offset_change_rows"], 12)
            self.assertEqual(result[label]["zone_change_observations"], 12)
            self.assertEqual(len(result[label]["examples"]), 10)
            self.assertEqual([example["source_row_number"] for example in result[label]["examples"]], list(range(42, 52)))
        self.assert_reconciled(result)

    def test_empty_population_is_reconciled(self):
        result = self.coverage([])
        for label in ("scheduled", "actual"):
            self.assertEqual(result[label], {"population_rows": 0, "checked": 0,
                                             "excluded_counts": {"missing_timestamps": 0},
                                             "offset_change_rows": 0, "zone_change_observations": 0,
                                             "examples": [], "reconciled": True})

    def test_result_is_json_ready_deterministic_and_inputs_remain_unchanged(self):
        report = self.report([flight_row("two-zones", destination="LAX", sibt="2025-03-09T10:30:00Z"),
                              flight_row("later")])
        zones = copy.deepcopy(ZONES)
        before_report, before_zones = report.to_dict(), copy.deepcopy(zones)
        first = self.helper.timezone_offset_coverage(report, zones)
        second = self.helper.timezone_offset_coverage(report, dict(reversed(list(zones.items()))))
        self.assertEqual(first, second)
        self.assertEqual(json.loads(json.dumps(first, allow_nan=False)), first)
        self.assertEqual(report.to_dict(), before_report)
        self.assertEqual(zones, before_zones)

    def test_invalid_or_missing_timezone_configuration_fails_without_guessing(self):
        for zones in (None, [], {"JFK": 123, "BOS": "America/New_York"},
                      {"JFK": "No/Such_Zone", "BOS": "America/New_York"},
                      {"JFK": "America/New_York"}, {**ZONES, "unused": "No/Such_Zone"}):
            with self.subTest(zones=zones):
                with self.assertRaises(ValueError):
                    self.helper.timezone_offset_coverage(self.report([flight_row()]), zones)

    def test_manually_created_naive_or_reversed_windows_are_rejected(self):
        record = normalize_record(flight_row(), row_number=42)
        for changes in ({"sobt": datetime(2025, 3, 9, 6, 30)}, {"sibt": record.flight.sobt},
                        {"aibt": record.flight.aobt.replace(hour=5)},
                        {"aobt": datetime(2025, 3, 9, 6, 30), "aibt": None}):
            with self.subTest(changes=changes):
                altered = replace(record, flight=replace(record.flight, **changes))
                with self.assertRaises(ValueError):
                    self.helper.timezone_offset_coverage(analyze_results([altered]), ZONES)

    def test_explicit_offset_instants_are_normalized_to_utc(self):
        result = self.coverage([flight_row("offset", sobt="2025-03-09T01:30:00-05:00",
                                        sibt="2025-03-09T03:30:00-04:00")])
        example = result["scheduled"]["examples"][0]
        self.assertEqual(example["window_start_utc"], "2025-03-09T06:30:00+00:00")
        self.assertEqual(example["window_end_utc"], "2025-03-09T07:30:00+00:00")

    def test_unrepresentable_utc_or_local_window_endpoints_fail_clearly(self):
        record = normalize_record(flight_row(), row_number=42)
        for start in (datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))),
                      datetime(1, 1, 1, tzinfo=timezone.utc)):
            with self.subTest(start=start):
                # The first underflows when converted to UTC; the second is valid
                # UTC but underflows when projected into the airport's IANA zone.
                altered = replace(record, flight=replace(
                    record.flight, sobt=start, sibt=datetime(1, 1, 2, tzinfo=timezone.utc)
                ))
                with self.assertRaises(ValueError):
                    self.helper.timezone_offset_coverage(analyze_results([altered]), ZONES)

    def test_compensating_changes_inside_a_long_window_are_not_claimed_as_detected(self):
        result = self.coverage([flight_row("year", service_date="2025-01-01",
                                        sobt="2025-01-01T12:00:00Z", sibt="2026-01-01T12:00:00Z",
                                        aobt="2025-01-01T12:00:00Z", aibt="2026-01-01T12:00:00Z")])
        for label in ("scheduled", "actual"):
            self.assertEqual(result[label]["checked"], 1)
            self.assertEqual(result[label]["offset_change_rows"], 0)
        policy = result["policy"]
        self.assertIs(policy["absolute_utc_validation"], False)
        self.assertIn("compensating", policy["limitations"])
        self.assertIn("not necessarily a DST", policy["interpretation"])


if __name__ == "__main__":
    unittest.main()
