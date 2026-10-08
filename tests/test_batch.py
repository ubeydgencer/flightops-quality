import unittest

from flightops_quality.batch import analyze_records
from test_canonical import valid_row


class BatchTests(unittest.TestCase):
    def test_exact_repeat_counts_once_for_metrics(self):
        row = valid_row()
        report = analyze_records([row, dict(row)])
        self.assertEqual(report.counts, {"input": 2, "accepted": 1, "quarantined": 0, "duplicates": 1})
        self.assertEqual(report.duplicates[0].issues[-1].code, "DUPLICATE_EXACT")
        self.assertEqual(report.duplicates[0].row_number, 2)

    def test_entire_conflict_group_is_quarantined_including_repeats(self):
        row = valid_row()
        other = {**row, "record_id": "other"}
        conflict = {**row, "flight_number": "200"}
        report = analyze_records([row, other, dict(row), conflict])
        self.assertEqual(report.counts, {"input": 4, "accepted": 1, "quarantined": 3, "duplicates": 0})
        self.assertEqual([r.row_number for r in report.quarantined], [1, 3, 4])
        self.assertTrue(all(r.issues[-1].code == "DUPLICATE_CONFLICT" for r in report.quarantined))

    def test_missing_identity_rows_are_not_collapsed(self):
        row = {**valid_row(), "record_id": ""}
        report = analyze_records([row, dict(row)])
        self.assertEqual(len(report.quarantined), 2)
        self.assertFalse(report.duplicates)

    def test_deterministic_replay(self):
        rows = [valid_row(), {**valid_row(), "record_id": "2"}, valid_row()]
        self.assertEqual(analyze_records(rows).to_dict(), analyze_records(rows).to_dict())


if __name__ == "__main__":
    unittest.main()
