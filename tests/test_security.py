import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from flightops_quality.cli import main
from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.adapters.bts import normalize_bts_row, parse_bts_clock
from flightops_quality.batch import analyze_results
from flightops_quality.models import BatchReport
from flightops_quality.reporting import audit_document, render_html

ROOT = Path(__file__).resolve().parents[1]


class SecurityTests(unittest.TestCase):
    def run_invalid(self, args):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                main(args)
        self.assertEqual(exc.exception.code, 2)

    def test_row_number_is_escaped_even_for_crafted_report_document(self):
        document = audit_document(BatchReport((), (), (), 0))
        document["quarantined"] = [{"row_number": "<script>alert(1)</script>",
                                    "flight": None, "issues": [], "raw": {}}]
        html = render_html(document)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_input_size_and_record_limits_prevent_partial_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "oversized.csv"
            source.write_bytes(b"a\n" + b"x" * 1_048_576)
            output = Path(folder) / "audit"
            self.run_invalid([str(source), "--output", str(output), "--max-input-mb", "1"])
            self.assertFalse(output.exists())
            self.run_invalid([str(ROOT / "examples/synthetic_flights.csv"), "--output",
                              str(output), "--max-records", "1"])
            self.assertFalse(output.exists())

    def test_conflicting_timezone_keys_are_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            mapping = Path(folder) / "timezones.json"
            mapping.write_text('{"JFK":"UTC","JFK":"America/New_York"}')
            output = Path(folder) / "audit"
            self.run_invalid([str(ROOT / "examples/synthetic_bts.csv"), "--format", "bts",
                              "--timezones", str(mapping), "--output", str(output)])
            self.assertFalse(output.exists())

    def test_deep_timezone_json_fails_without_traceback(self):
        with tempfile.TemporaryDirectory() as folder:
            mapping = Path(folder) / "timezones.json"
            mapping.write_text('[' * 2000 + '0' + ']' * 2000)
            self.run_invalid([str(ROOT / "examples/synthetic_bts.csv"), "--format", "bts",
                              "--timezones", str(mapping), "--output", str(Path(folder) / "audit")])

    def test_negative_limits_are_rejected(self):
        self.run_invalid([str(ROOT / "examples/synthetic_flights.csv"), "--output", "unused",
                          "--max-input-mb", "-1"])

    def test_extreme_decimal_exponent_is_a_row_finding(self):
        from test_bts import bts_row, ZONES
        with self.assertRaises(ValueError):
            parse_bts_clock("1e999999999")
        result = normalize_bts_row({**bts_row(), "TaxiOut": "1e999999999"}, ZONES)
        self.assertFalse(result.accepted)
        self.assertIn("BTS_NUMBER_INVALID", [i.code for i in result.issues])

    def test_nested_raw_data_is_a_snapshot(self):
        from test_canonical import valid_row
        row = {**valid_row(), "extra": {"values": [1, 2]}}
        normalized = normalize_record(row)
        row["extra"]["values"].append(3)
        self.assertEqual(normalized.raw["extra"]["values"], [1, 2])
        report = analyze_results([normalized])
        normalized.raw["extra"]["values"].append(4)
        self.assertEqual(report.accepted[0].raw["extra"]["values"], [1, 2])

    def test_nested_keys_and_surrogates_fail_with_clear_contract_error(self):
        from test_canonical import valid_row
        for extra in ({1: "a", "1": "b"}, "\ud800", {"\ud800": "value"}):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    normalize_record({**valid_row(), "extra": extra})

    def test_cell_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "audit"
            self.run_invalid([str(ROOT / "examples/synthetic_flights.csv"), "--output",
                              str(output), "--max-cells", "1"])
            self.assertFalse(output.exists())

    def test_cyclic_or_excessively_nested_api_data_is_rejected(self):
        from test_canonical import valid_row
        cyclic = {}
        cyclic["self"] = cyclic
        deep = 0
        for _ in range(40):
            deep = [deep]
        for value in (cyclic, deep, 1 << 5000):
            with self.assertRaises(ValueError):
                normalize_record({**valid_row(), "extra": value})

    def test_wide_header_is_rejected_before_building_records(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "wide.csv"
            source.write_text(",".join(f"column{i}" for i in range(257)) + "\n")
            output = Path(folder) / "audit"
            self.run_invalid([str(source), "--output", str(output)])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
