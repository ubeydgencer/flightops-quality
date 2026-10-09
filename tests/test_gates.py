import json
import unittest
from dataclasses import FrozenInstanceError

from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.batch import analyze_records
from flightops_quality.gates import QualityPolicy, evaluate_quality
from flightops_quality.models import BatchReport, Issue, RecordResult


def flight_row(identity="1", **changes):
    row = dict(source="demo", record_id=identity, service_date="2026-10-09",
               carrier="DEMO", flight_number="100", origin="IST", destination="FRA",
               sobt="2026-10-09T06:00:00Z", sibt="2026-10-09T09:00:00Z",
               aobt="2026-10-09T06:00:00Z", aibt="2026-10-09T09:00:00Z")
    return {**row, **changes}


class QualityPolicyTests(unittest.TestCase):
    def test_defaults_and_frozen_policy(self):
        policy = QualityPolicy()
        self.assertEqual(policy.to_dict(), {
            "min_arrival_coverage_percent": None,
            "min_otp_eligible_flights": None,
            "max_quarantine_rate_percent": None,
        })
        with self.assertRaises(FrozenInstanceError):
            policy.min_otp_eligible_flights = 1

    def test_percentage_contract(self):
        for field in ("min_arrival_coverage_percent", "max_quarantine_rate_percent"):
            for value in (True, False, "50", float("nan"), float("inf"),
                          float("-inf"), -1, 101, 10**1000, [], {}):
                with self.subTest(field=field, value=type(value).__name__):
                    with self.assertRaises(ValueError):
                        QualityPolicy(**{field: value})
            for value in (0, 100, 50.5):
                self.assertEqual(getattr(QualityPolicy(**{field: value}), field), value)

    def test_minimum_count_contract_and_zero(self):
        for value in (True, False, "1", 1.0, -1, 2**63, float("nan"), [], {}):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(ValueError):
                    QualityPolicy(min_otp_eligible_flights=value)
        self.assertEqual(QualityPolicy(min_otp_eligible_flights=2**63 - 1).min_otp_eligible_flights,
                         2**63 - 1)
        quality = evaluate_quality(BatchReport((), (), (), 0),
                                   QualityPolicy(min_otp_eligible_flights=0))
        self.assertEqual(quality["status"], "passed")
        self.assertEqual(quality["checks"][0]["observed"], 0)


class QualityGateTests(unittest.TestCase):
    def test_not_configured_still_reports_measurements(self):
        quality = evaluate_quality(analyze_records([flight_row()]))
        self.assertEqual(quality["status"], "not_configured")
        self.assertEqual(quality["checks"], [])
        self.assertEqual(quality["measurements"]["arrival_coverage_percent"]["value"], 100)
        self.assertEqual(json.loads(json.dumps(quality)), quality)

    def test_empty_percentage_populations_fail_even_zero_threshold(self):
        report = BatchReport((), (), (), 0)
        quality = evaluate_quality(report, QualityPolicy(min_arrival_coverage_percent=0,
                                                        max_quarantine_rate_percent=0))
        self.assertEqual(quality["status"], "failed")
        for check in quality["checks"]:
            self.assertIsNone(check["observed"])
            self.assertFalse(check["passed"])
            self.assertIn("population is empty", check["reason"])

    def test_all_cancelled_and_diverted_are_not_missing_normal_arrivals(self):
        rows = [flight_row("1", cancelled=True, aobt="", aibt=""),
                flight_row("2", diverted=True, aibt="")]
        quality = evaluate_quality(analyze_records(rows),
                                   QualityPolicy(min_arrival_coverage_percent=0))
        coverage = quality["measurements"]["arrival_coverage_percent"]
        self.assertEqual((coverage["numerator"], coverage["denominator"]), (0, 0))
        self.assertIsNone(coverage["value"])
        self.assertEqual(quality["status"], "failed")

    def test_all_missing_arrivals_have_observed_zero_coverage(self):
        report = analyze_records([flight_row("1", aibt=""), flight_row("2", sibt="")])
        quality = evaluate_quality(report, QualityPolicy(min_arrival_coverage_percent=0,
                                                        min_otp_eligible_flights=0))
        coverage = quality["measurements"]["arrival_coverage_percent"]
        self.assertEqual((coverage["value"], coverage["numerator"], coverage["denominator"]),
                         (0, 0, 2))
        self.assertEqual(quality["status"], "passed")
        self.assertEqual(evaluate_quality(report, QualityPolicy(min_arrival_coverage_percent=1))["status"],
                         "failed")

    def test_sparse_otp_does_not_imply_sufficient_coverage(self):
        rows = [flight_row()] + [flight_row(str(i), aibt="") for i in range(2, 101)]
        quality = evaluate_quality(analyze_records(rows),
                                   QualityPolicy(min_arrival_coverage_percent=90,
                                                 min_otp_eligible_flights=2))
        self.assertEqual(quality["measurements"]["arrival_coverage_percent"]["value"], 1)
        self.assertEqual(quality["measurements"]["otp_eligible_flights"]["value"], 1)
        self.assertEqual(quality["status"], "failed")
        self.assertTrue(all(not check["passed"] for check in quality["checks"]))

    def test_exact_repeats_do_not_dilute_quarantine_rate(self):
        good = flight_row()
        bad = flight_row("bad", service_date="invalid")
        report = analyze_records([good, bad] + [dict(good) for _ in range(50)])
        quality = evaluate_quality(report, QualityPolicy(max_quarantine_rate_percent=49))
        rate = quality["measurements"]["quarantine_rate_percent"]
        self.assertEqual((rate["value"], rate["numerator"], rate["denominator"]), (50, 1, 2))
        self.assertEqual(quality["status"], "failed")
        self.assertIn("exact repeats excluded", rate["population"])

    def test_all_conflict_members_stay_in_quarantine_population(self):
        row = flight_row()
        report = analyze_records([row, dict(row), {**row, "flight_number": "200"}])
        quality = evaluate_quality(report, QualityPolicy(max_quarantine_rate_percent=100))
        rate = quality["measurements"]["quarantine_rate_percent"]
        self.assertEqual((rate["value"], rate["numerator"], rate["denominator"]), (100, 3, 3))
        self.assertIn("every conflict-group member", rate["population"])
        self.assertEqual(quality["status"], "passed")

    def test_thresholds_are_inclusive_and_all_checks_are_reported(self):
        report = analyze_records([flight_row(), flight_row("2", aibt=""),
                                  flight_row("bad", service_date="invalid")])
        quarantine_rate = 100 / 3
        quality = evaluate_quality(report, QualityPolicy(min_arrival_coverage_percent=50,
                                                        min_otp_eligible_flights=1,
                                                        max_quarantine_rate_percent=quarantine_rate))
        self.assertEqual(quality["status"], "passed")
        self.assertEqual([check["operator"] for check in quality["checks"]], [">=", ">=", "<="])
        self.assertTrue(all(check["passed"] for check in quality["checks"]))
        self.assertEqual(len(quality["checks"]), 3)

    def test_invalid_policy_object_fails_clearly(self):
        with self.assertRaises(ValueError):
            evaluate_quality(BatchReport((), (), (), 0), {"min_otp_eligible_flights": 1})


class BatchReportInvariantTests(unittest.TestCase):
    def test_accepted_category_cannot_contain_error_record(self):
        record = normalize_record(flight_row())
        invalid = RecordResult(record.flight,
                               (Issue("MANUAL_ERROR", "error", ("aibt",), "Requires quarantine"),),
                               record.raw)
        with self.assertRaisesRegex(ValueError, "without error findings"):
            BatchReport((invalid,), (), (), 1)

    def test_accepted_category_cannot_contain_unresolved_identity(self):
        invalid = RecordResult(None, (), {})
        with self.assertRaisesRegex(ValueError, "normalized flight"):
            BatchReport((invalid,), (), (), 1)

    def test_accepted_warning_is_allowed(self):
        record = normalize_record(flight_row(aibt=""))
        self.assertTrue(record.accepted)
        self.assertTrue(any(issue.severity == "warning" for issue in record.issues))
        self.assertEqual(BatchReport((record,), (), (), 1).counts["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
