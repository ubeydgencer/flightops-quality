import importlib.util
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flightops_quality.cli import main

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()
        self.addCleanup(self.silence.__exit__, None, None, None)

    def test_cli_to_warehouse_reconciles_all_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "audit"
            code = main([str(ROOT / "examples/synthetic_flights.csv"), "--output", str(output)])
            self.assertEqual(code, 0)
            audit = json.loads((output / "audit.json").read_text())
            self.assertEqual(audit["counts"], {
                "input": 11, "accepted": 6, "quarantined": 4, "duplicates": 1,
            })
            self.assertEqual(audit["summary"]["arrival_otp_15_completed"]["eligible"], 2)
            self.assertEqual(audit["summary"]["arrival_otp_15_completed"]["percent"], 50)
            spec = importlib.util.spec_from_file_location("etl", ROOT / "examples/etl_sqlite.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.load(output / "audit.json", output / "warehouse.db")
            self.assertEqual(result["raw_records"], 11)
            self.assertEqual(result["routes"][0]["accepted_flights"], 6)
            self.assertEqual(result["routes"][0]["arrival_otp_15_completed_percent"], 50)
            self.assertEqual(result["routes"][0]["arrival_coverage_population"], 3)
            self.assertEqual(result["routes"][0]["missing_arrival_delay"], 1)
            self.assertAlmostEqual(result["routes"][0]["arrival_delay_coverage_percent"], 200 / 3)
            self.assertEqual(audit["quality_gate"]["status"], "not_configured")

    def test_strict_exit_and_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "audit"
            self.assertEqual(main([str(ROOT / "examples/synthetic_flights.csv"),
                                   "--output", str(output), "--fail-on-error"]), 1)
            prior = (output / "audit.json").read_bytes()
            with self.assertRaises(SystemExit) as exc:
                main([str(ROOT / "examples/synthetic_flights.csv"), "--output", str(output)])
            self.assertEqual(exc.exception.code, 2)
            self.assertEqual((output / "audit.json").read_bytes(), prior)

    def test_python_module_entry_point(self):
        run = subprocess.run([sys.executable, "-m", "flightops_quality", "--version"],
                             capture_output=True, text=True, check=True)
        self.assertEqual(run.stdout.strip(), "0.2.0")

    def test_configured_gates_pass_at_exact_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "audit"
            code = main([str(ROOT / "examples/synthetic_flights.csv"), "--output", str(output),
                         "--min-arrival-coverage-percent", str(200 / 3), "--min-otp-eligible-flights", "2",
                         "--max-quarantine-rate-percent", "40"])
            self.assertEqual(code, 0)
            audit = json.loads((output / "audit.json").read_text())
            self.assertEqual(audit["quality_gate"]["status"], "passed")
            self.assertAlmostEqual(audit["summary"]["arrival_otp_15_completed"]["coverage_percent"], 200 / 3)
            self.assertEqual(audit["quality_gate"]["policy"]["max_quarantine_rate_percent"], 40)

    def test_failed_gate_retains_complete_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "audit"
            code = main([str(ROOT / "examples/synthetic_flights.csv"), "--output", str(output),
                         "--min-arrival-coverage-percent", "80", "--min-otp-eligible-flights", "10",
                         "--max-quarantine-rate-percent", "5"])
            self.assertEqual(code, 1)
            self.assertEqual({p.name for p in output.iterdir()}, {
                "audit.json", "audit.html", "accepted.jsonl", "quarantined.jsonl", "duplicates.jsonl",
            })
            audit = json.loads((output / "audit.json").read_text())
            self.assertEqual(audit["quality_gate"]["status"], "failed")
            self.assertEqual(len(audit["quality_gate"]["checks"]), 3)
            self.assertIn("Batch quality gate", (output / "audit.html").read_text())

    def test_sparse_arrival_data_cannot_pass_coverage_requirement(self):
        import csv
        from test_canonical import valid_row
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sparse.csv"
            row = {**valid_row(), "record_id": "observed",
                   "sibt": "2026-10-09T12:00:00Z", "aibt": "2026-10-09T12:00:00Z",
                   "atot": "", "aldt": ""}
            missing = {**row, **{key: "" for key in ("sobt", "sibt", "aobt", "aibt", "atot", "aldt")}}
            with source.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
                for index in range(99):
                    writer.writerow({**missing, "record_id": str(index)})
            output = Path(folder) / "audit"
            self.assertEqual(main([str(source), "--output", str(output),
                                   "--min-arrival-coverage-percent", "80"]), 1)
            audit = json.loads((output / "audit.json").read_text())
            otp = audit["summary"]["arrival_otp_15_completed"]
            self.assertEqual(audit["counts"]["accepted"], 100)
            self.assertEqual(otp["percent"], 100)
            self.assertEqual(otp["coverage_population"], 100)
            self.assertEqual(otp["coverage_percent"], 1)
            self.assertEqual(audit["quality_gate"]["status"], "failed")

    def test_invalid_gate_configuration_writes_nothing(self):
        for flags in (["--min-arrival-coverage-percent", "nan"],
                      ["--max-quarantine-rate-percent", "inf"],
                      ["--min-arrival-coverage-percent", "101"],
                      ["--max-quarantine-rate-percent", "-1"],
                      ["--min-otp-eligible-flights", "-1"]):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / "audit"
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                    main([str(ROOT / "examples/synthetic_flights.csv"), "--output", str(output), *flags])
                self.assertEqual(exc.exception.code, 2)
                self.assertFalse(output.exists())

    def test_malformed_csv_produces_no_partial_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "broken.csv"
            source.write_text("source,record_id\ndemo,x,extra\n", encoding="utf-8")
            output = Path(folder) / "audit"
            with self.assertRaises(SystemExit) as exc:
                main([str(source), "--output", str(output)])
            self.assertEqual(exc.exception.code, 2)
            self.assertFalse(output.exists())

    def test_bts_cli_records_configuration_and_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "audit"
            code = main([str(ROOT / "examples/synthetic_bts.csv"), "--format", "bts",
                         "--timezones", str(ROOT / "examples/airport_timezones.json"),
                         "--midnight-policy", "end", "--output", str(output)])
            self.assertEqual(code, 0)
            audit = json.loads((output / "audit.json").read_text())
            self.assertEqual(audit["counts"], {
                "input": 5, "accepted": 4, "quarantined": 1, "duplicates": 0,
            })
            self.assertEqual(audit["manifest"]["bts_midnight_policy"], "end")
            self.assertEqual(len(audit["manifest"]["timezone_mapping_sha256"]), 64)

    def test_multiline_csv_reports_source_start_line(self):
        import csv
        from test_canonical import valid_row
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "multiline.csv"
            row = {**valid_row(), "note": "first\nsecond"}
            with source.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
                writer.writerow({**row, "record_id": "2", "note": "single"})
            output = Path(folder) / "audit"
            main([str(source), "--output", str(output)])
            audit = json.loads((output / "audit.json").read_text())
            self.assertEqual([r["row_number"] for r in audit["accepted"]], [2, 4])

    def test_blank_lines_do_not_shift_source_lineage(self):
        import csv
        from test_canonical import valid_row
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "blank-lines.csv"
            row = valid_row()
            with source.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                handle.write("\n")
                writer.writerow(row)
            output = Path(folder) / "audit"
            main([str(source), "--output", str(output)])
            audit = json.loads((output / "audit.json").read_text())
            self.assertEqual(audit["accepted"][0]["row_number"], 3)


if __name__ == "__main__":
    unittest.main()
