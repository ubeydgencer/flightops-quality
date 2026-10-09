import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_bts import ZONES, bts_row

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bts_validation", ROOT / "examples/bts_validation.py")
VALIDATION = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(ROOT / "examples"), *sys.path]):
    SPEC.loader.exec_module(VALIDATION)


class BtsValidationTests(unittest.TestCase):
    def validate(self, *rows):
        result = VALIDATION.validate_rows(((number, row) for number, row in enumerate(rows, start=2)), ZONES)
        self.assertEqual(result["input_rows"], len(rows))
        for check in result["holdout_checks"].values():
            self.assertTrue(check["reconciled"])
            self.assertEqual(check["checked"] + sum(check["excluded_counts"].values()), len(rows))
            self.assertEqual(check["matched"] + check["mismatched"], check["checked"])
        coverage = result["timezone_offset_transitions"]
        self.assertEqual(coverage["scheduled"]["population_rows"], result["group_dispositions"]["accepted"])
        self.assertEqual(coverage["actual"]["population_rows"],
                         result["batch_summary"]["arrival_otp_15_completed"]["coverage_population"])
        for window in ("scheduled", "actual"):
            item = coverage[window]
            self.assertTrue(item["reconciled"])
            self.assertEqual(item["checked"] + sum(item["excluded_counts"].values()), item["population_rows"])
        json.dumps(result, allow_nan=False)
        return result

    def test_arrival_holdout_detects_mismatch_original_adapter_quarantines(self):
        result = self.validate({**bts_row(), "ArrDelay": "-19"})
        self.assertEqual(result["group_dispositions"]["quarantined"], 1)
        self.assertEqual(result["normalizer_issue_counts"]["BTS_DURATION_MISMATCH"], 1)
        check = result["holdout_checks"]["ArrDelay"]
        self.assertEqual((check["checked"], check["matched"], check["mismatched"]), (1, 0, 1))
        example = check["mismatch_examples"][0]
        self.assertEqual((example["source_row_number"], example["predicted"], example["reported"]), (2, -20, -19))
        self.assertEqual(result["holdout_checks"]["AirTime"]["matched"], 1)

    def test_airborne_holdout_detects_mismatch_original_adapter_quarantines(self):
        result = self.validate({**bts_row(), "AirTime": "314"})
        self.assertEqual(result["group_dispositions"]["quarantined"], 1)
        check = result["holdout_checks"]["AirTime"]
        self.assertEqual((check["checked"], check["mismatched"]), (1, 1))
        self.assertEqual((check["mismatch_examples"][0]["predicted"], check["mismatch_examples"][0]["reported"]),
                         (315, 314))

    def test_cancelled_diverted_and_invalid_status_are_counted_and_excluded(self):
        result = self.validate({**bts_row(), "Cancelled": "1"},
                               {**bts_row(), "Diverted": "1", "Flight_Number_Reporting_Airline": "2"},
                               {**bts_row(), "Cancelled": "bad", "Flight_Number_Reporting_Airline": "3"},
                               {**bts_row(), "Cancelled": "1", "Diverted": "1", "Flight_Number_Reporting_Airline": "4"})
        self.assertEqual(result["source_status_counts"]["Cancelled"], {"0": 1, "1": 2, "invalid": 1})
        self.assertEqual(result["source_status_counts"]["Diverted"], {"0": 2, "1": 2, "invalid": 0})
        for check in result["holdout_checks"].values():
            self.assertEqual(check["checked"], 0)
            self.assertEqual(check["excluded_counts"], {"cancelled": 2, "diverted": 1, "invalid_status": 1})

    def test_missing_target_is_explicit_and_other_target_remains_comparable(self):
        result = self.validate({**bts_row(), "ArrDelay": ""})
        self.assertEqual(result["holdout_checks"]["ArrDelay"]["excluded_counts"], {"missing_target": 1})
        self.assertEqual(result["holdout_checks"]["AirTime"]["matched"], 1)
        self.assertEqual(result["source_missing_fields"]["ArrDelay"], 1)

    def test_missing_clock_is_visible_but_duration_evidence_still_compares(self):
        result = self.validate({**bts_row(), "DepTime": ""})
        self.assertEqual(result["source_missing_fields"]["DepTime"], 1)
        self.assertEqual(result["holdout_checks"]["ArrDelay"]["matched"], 1)
        self.assertEqual(result["holdout_checks"]["AirTime"]["matched"], 1)

    def test_missing_delay_is_not_guessed_from_clock(self):
        result = self.validate({**bts_row(), "DepDelay": ""})
        for check in result["holdout_checks"].values():
            self.assertEqual(check["excluded_counts"], {"missing_derivation_fields": 1})
        self.assertEqual(result["unresolved_counts"]["BTS_TIME_UNRESOLVED"], 1)

    def test_unknown_midnight_policy_stays_unresolved(self):
        result = self.validate({**bts_row(), "CRSDepTime": "2400"})
        self.assertEqual(result["unresolved_counts"]["BTS_MIDNIGHT_UNRESOLVED"], 1)
        self.assertIsNone(result["policy"]["midnight_policy"])
        for check in result["holdout_checks"].values():
            self.assertEqual(check["excluded_counts"], {"midnight_policy_unresolved": 1})

    def test_dst_fold_is_never_chosen_for_validation(self):
        result = self.validate({**bts_row(), "FlightDate": "2026-11-01", "CRSDepTime": "0130"})
        self.assertEqual(result["unresolved_counts"]["TIME_AMBIGUOUS"], 1)
        for check in result["holdout_checks"].values():
            self.assertEqual(check["excluded_counts"], {"dst_ambiguous": 1})

    def test_original_duplicates_and_conflicts_are_grouped_once(self):
        second = {**bts_row(), "Flight_Number_Reporting_Airline": "2"}
        result = self.validate(bts_row(), bts_row(), second, {**second, "ArrDelay": "-19"})
        self.assertEqual(result["group_dispositions"], {"input": 4, "accepted": 1, "quarantined": 2, "duplicates": 1})
        self.assertEqual(result["batch_summary"]["issue_counts"]["DUPLICATE_CONFLICT"], 2)
        self.assertEqual(result["holdout_checks"]["ArrDelay"]["checked"], 4)
        self.assertEqual(result["holdout_checks"]["ArrDelay"]["mismatched"], 1)

    def test_raw_source_and_nested_values_remain_unchanged(self):
        row = {**bts_row(), "extra": {"nested": [1, 2]}}
        expected = copy.deepcopy(row)
        self.validate(row)
        self.assertEqual(row, expected)
        self.assertEqual(row["ArrDelay"], "-20")
        self.assertEqual(row["AirTime"], "315")

    def test_invalid_numeric_target_is_not_silently_dropped(self):
        for value in ("nan", "1.5", "-1", "not-a-number", "1e999999999"):
            with self.subTest(value=value):
                result = self.validate({**bts_row(), "AirTime": value})
                self.assertEqual(result["holdout_checks"]["AirTime"]["excluded_counts"], {"invalid_target": 1})
                self.assertEqual(result["holdout_checks"]["ArrDelay"]["matched"], 1)

    def test_invalid_source_clock_is_an_explicit_probe_exclusion(self):
        result = self.validate({**bts_row(), "DepTime": "1260"})
        for check in result["holdout_checks"].values():
            self.assertEqual(check["excluded_counts"], {"invalid_derivation_input": 1})

    def test_probe_clock_mismatch_is_not_claimed_as_valid_parity(self):
        result = self.validate({**bts_row(), "CRSArrTime": "0300"})
        for check in result["holdout_checks"].values():
            self.assertEqual(check["excluded_counts"], {"probe_clock_mismatch": 1})

    def test_routes_dates_and_official_airport_ids_remain_visible(self):
        row = {**bts_row(), "OriginAirportID": "12478", "OriginAirportSeqID": "1247805",
               "DestAirportID": "12892", "DestAirportSeqID": "1289208"}
        result = self.validate(row)
        self.assertEqual(result["route_counts"], {"JFK-LAX": 1})
        self.assertEqual(result["date_range"], {"start": "2026-07-01", "end": "2026-07-01", "valid_rows": 1, "invalid_rows": 0})
        self.assertEqual(result["airport_ids"]["JFK"]["airport_ids"], ["12478"])
        self.assertEqual(result["airport_ids"]["LAX"]["airport_sequence_ids"], ["1289208"])

    def test_mismatch_examples_are_bounded_to_ten(self):
        rows = [{**bts_row(), "ArrDelay": "-19", "Flight_Number_Reporting_Airline": str(i)} for i in range(15)]
        result = self.validate(*rows)
        check = result["holdout_checks"]["ArrDelay"]
        self.assertEqual(check["mismatched"], 15)
        self.assertEqual(len(check["mismatch_examples"]), 10)
        self.assertEqual([e["source_row_number"] for e in check["mismatch_examples"]], list(range(2, 12)))

    def test_normalizer_examples_explain_original_fields_and_derived_utc(self):
        row = {**bts_row(), "ArrDelay": "-19", "OriginAirportID": "12478", "OriginAirportSeqID": "1247805",
               "DestAirportID": "12892", "DestAirportSeqID": "1289208", "UnrelatedColumn": "exclude this"}
        result = self.validate(row)
        example = result["normalizer_issue_examples"][0]
        self.assertEqual(example["source_row_number"], 2)
        self.assertEqual(example["record_id"], example["flight"]["record_id"])
        self.assertEqual(example["raw_fields"]["ArrDelay"], "-19")
        self.assertEqual(example["raw_fields"]["AirTime"], "315")
        self.assertEqual(example["raw_sha256"], hashlib.sha256(json.dumps(
            row, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
            allow_nan=False).encode("utf-8")).hexdigest())
        self.assertEqual(example["raw_fields"]["OriginAirportSeqID"], "1247805")
        self.assertNotIn("UnrelatedColumn", example["raw_fields"])
        self.assertEqual(example["flight"]["sibt"], "2026-07-02T09:00:00+00:00")
        self.assertEqual(example["flight"]["aibt"], "2026-07-02T08:40:00+00:00")
        self.assertEqual(example["issues"][0]["code"], "BTS_DURATION_MISMATCH")
        self.assertEqual(example["issues"][0]["fields"], ["ArrDelay", "ActualElapsedTime", "DepDelay", "CRSElapsedTime"])
        self.assertEqual(example["issues"][0]["severity"], "error")

    def test_normalizer_examples_are_bounded_to_ten_original_rows(self):
        rows = [{**bts_row(), "ArrDelay": "-19", "Flight_Number_Reporting_Airline": str(i)} for i in range(15)]
        result = self.validate(*rows)
        examples = result["normalizer_issue_examples"]
        self.assertEqual(len(examples), 10)
        self.assertEqual([e["source_row_number"] for e in examples], list(range(2, 12)))
        self.assertEqual(result["normalizer_issue_counts"]["BTS_DURATION_MISMATCH"], 15)

    def test_group_conflicts_do_not_fabricate_normalizer_examples(self):
        row = bts_row()
        result = self.validate(row, {**row, "UnrelatedColumn": "a source revision"})
        self.assertEqual(result["group_dispositions"]["quarantined"], 2)
        self.assertEqual(result["normalizer_issue_examples"], [])

    def test_empty_cohort_reconciles_without_success_claims(self):
        result = self.validate()
        for check in result["holdout_checks"].values():
            self.assertEqual(check["checked"], 0)
        self.assertIsNone(result["date_range"]["start"])
        self.assertFalse(result["policy"]["absolute_utc_validation"])

    def test_source_kpi_parity_keeps_raw_and_accepted_populations_separate(self):
        row = bts_row()
        result = self.validate(row, row, {**row, "ArrDelay": "15", "Flight_Number_Reporting_Airline": "2"})
        raw = result["source_input_kpis"]["all_source_rows"]
        accepted = result["source_input_kpis"]["accepted_unique_rows"]
        self.assertEqual((raw["eligible"], raw["on_time"], raw["late"]), (3, 2, 1))
        self.assertEqual((accepted["eligible"], accepted["on_time"], accepted["late"]), (1, 1, 0))
        self.assertTrue(all(p["matched"] for p in result["source_input_kpis"]["accepted_parity"].values()))

    def test_missing_source_delay_is_not_fabricated_for_parity(self):
        result = self.validate({**bts_row(), "ArrDelay": ""})
        parity = result["source_input_kpis"]["accepted_parity"]["eligible"]
        self.assertEqual(parity, {"source": 0, "derived": 1, "matched": False})
        raw = result["source_input_kpis"]["all_source_rows"]
        self.assertEqual(raw["excluded_counts"], {"missing_arrival_delay": 1})
        self.assertIsNone(raw["percent"])

    def test_one_third_source_percentage_does_not_fail_parity_from_rounding(self):
        late = {**bts_row(), "DepDelay": "30", "ArrDelay": "20", "DepTime": "",
                "ArrTime": "", "WheelsOff": "", "WheelsOn": ""}
        result = self.validate(bts_row(), {**late, "Flight_Number_Reporting_Airline": "2"},
                               {**late, "Flight_Number_Reporting_Airline": "3"})
        self.assertEqual(result["group_dispositions"]["accepted"], 3)
        parity = result["source_input_kpis"]["accepted_parity"]
        self.assertEqual(parity["percent"], {"source": 100 / 3, "derived": 100 / 3, "matched": True})
        self.assertTrue(all(item["matched"] for item in parity.values()))

    def test_invalid_source_line_number_is_a_contract_error(self):
        for number in (0, -1, True, "2"):
            with self.subTest(number=number):
                with self.assertRaises(ValueError):
                    VALIDATION.validate_rows([(number, bts_row())], ZONES)


if __name__ == "__main__":
    unittest.main()
