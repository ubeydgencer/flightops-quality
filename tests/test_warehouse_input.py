import importlib.util
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.batch import analyze_results
from flightops_quality.gates import QualityPolicy
from flightops_quality.reporting import audit_document
from test_canonical import valid_row

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("warehouse_input_etl", ROOT / "examples/etl_sqlite.py")
ETL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ETL)


class WarehouseInputTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.parent = Path(folder.name)
        self.audit_path = self.parent / "audit.json"
        self.database = self.parent / "new-output" / "warehouse.db"
        observed = {**valid_row(), "record_id": "observed", "provider_note": "İstanbul uçuşu"}
        missing = {**observed, "record_id": "missing-arrival", "aibt": None}
        invalid = {**observed, "record_id": "quarantined", "aibt": "2026-10-09T04:00:00Z"}
        self.report = analyze_results(normalize_record(row, row_number=number)
                                      for number, row in enumerate((observed, missing, invalid, observed), start=11))
        self.document = audit_document(self.report, quality_policy=QualityPolicy(
            min_arrival_coverage_percent=50, min_otp_eligible_flights=1,
        ))
        self.assertEqual(self.document["counts"], {
            "input": 4, "accepted": 2, "quarantined": 1, "duplicates": 1,
        })

    def write(self, document=None, suffix=b""):
        if document is None:
            document = self.document
        payload = json.dumps(document, ensure_ascii=False, indent=1).encode("utf-8") + suffix
        self.audit_path.write_bytes(payload)
        return payload

    def assert_no_output(self, original):
        self.assertFalse(os.path.lexists(self.database))
        self.assertFalse(self.database.parent.exists())
        self.assertEqual(self.audit_path.read_bytes(), original)

    def cli(self, *flags, audit_path=None):
        return subprocess.run(
            [sys.executable, str(ROOT / "examples/etl_sqlite.py"),
             str(audit_path or self.audit_path), str(self.database), *flags],
            capture_output=True, text=True, cwd=ROOT, timeout=10,
        )

    def assert_cli_rejected(self, run):
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(run.stdout, "")
        self.assertIn("etl_sqlite:", run.stderr)
        self.assertNotIn("Traceback", run.stderr)
        self.assertFalse(os.path.lexists(self.database))
        self.assertFalse(self.database.parent.exists())

    def test_exact_byte_and_combined_record_boundaries_preserve_all_rows_and_metadata(self):
        payload = self.write(suffix=b"\n \t\r\n")
        result = ETL.load(self.audit_path, self.database,
                          max_audit_bytes=len(payload), max_records=4)
        self.assertEqual(result["raw_records"], 4)
        self.assertEqual(result["quality_gate_status"], "passed")
        with sqlite3.connect(self.database) as connection:
            stored = connection.execute(
                "SELECT package_version, counts_json, summary_json, quality_gate_json FROM audit_metadata"
            ).fetchone()
            dispositions = dict(connection.execute(
                "SELECT disposition, COUNT(*) FROM raw_records GROUP BY disposition"
            ))
            manifest = json.loads(connection.execute("SELECT document FROM manifest").fetchone()[0])
            flight_count = connection.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        self.assertEqual(stored[0], self.document["package_version"])
        self.assertEqual([json.loads(value) for value in stored[1:]],
                         [self.document[key] for key in ("counts", "summary", "quality_gate")])
        self.assertEqual(manifest, self.document["manifest"])
        self.assertEqual(dispositions, {"accepted": 2, "quarantined": 1, "duplicates": 1})
        self.assertEqual(flight_count, 2)
        self.assertEqual(self.audit_path.read_bytes(), payload)

    def test_byte_limit_includes_unicode_encoding_and_trailing_whitespace(self):
        payload = self.write(suffix=b"\n \t\r\n")
        character_count = len(payload.decode("utf-8"))
        self.assertLess(character_count, len(payload))
        for limit in (len(payload) - 1, character_count):
            with self.subTest(max_audit_bytes=limit):
                with patch.object(ETL.json, "loads", side_effect=AssertionError("must not parse oversized input")):
                    with self.assertRaises(ValueError):
                        ETL.load(self.audit_path, self.database, max_audit_bytes=limit)
                self.assert_no_output(payload)

    def test_combined_record_limit_rejects_before_hashing_or_normalization_including_override(self):
        documents = (self.document, audit_document(self.report, quality_policy=QualityPolicy(
            min_otp_eligible_flights=2,
        )))
        for document in documents:
            payload = self.write(document)
            for override in (False, True):
                with self.subTest(gate=document["quality_gate"]["status"], override=override):
                    with patch.object(ETL, "_validate_raw_hashes", side_effect=AssertionError("must not hash")), \
                            patch.object(ETL, "_audit_report", side_effect=AssertionError("must not normalize")):
                        with self.assertRaises(ValueError):
                            ETL.load(self.audit_path, self.database, max_records=3,
                                     allow_failed_quality_gate=override)
                    self.assert_no_output(payload)

    def test_invalid_api_limits_fail_before_source_reading_or_output_creation(self):
        self.assertFalse(self.audit_path.exists())
        values = (True, False, 0, -1, 1.0, "4", None, 2**63)
        for name in ("max_audit_bytes", "max_records"):
            for value in values:
                with self.subTest(limit=name, value=value):
                    with patch.object(ETL, "_read_audit", side_effect=AssertionError("must not read source")):
                        with self.assertRaises(ValueError):
                            ETL.load(self.audit_path, self.database, **{name: value})
                    self.assertFalse(self.audit_path.exists())
                    self.assertFalse(os.path.lexists(self.database))
                    self.assertFalse(self.database.parent.exists())

    def test_larger_valid_limits_up_to_signed_64_bit_maximum_accept_small_audit(self):
        payload = self.write()
        result = ETL.load(self.audit_path, self.database,
                          max_audit_bytes=2**63 - 1, max_records=2**63 - 1)
        self.assertEqual(result["raw_records"], 4)
        self.assertEqual(self.audit_path.read_bytes(), payload)

    def test_understated_file_size_cannot_read_or_parse_beyond_limit_plus_one(self):
        payload = self.write(suffix=b" " * 200_000)
        limit = 100_000
        actual_fstat = os.fstat
        actual_read = os.read
        requested = []
        returned = []

        def understated_size(descriptor):
            info = actual_fstat(descriptor)
            return SimpleNamespace(st_mode=info.st_mode, st_size=0)

        def bounded_read(descriptor, size):
            requested.append(size)
            data = actual_read(descriptor, size)
            returned.append(len(data))
            return data

        # A stale small size models a file that grows after the initial fstat.
        with patch.object(ETL.os, "fstat", side_effect=understated_size), \
                patch.object(ETL.os, "read", side_effect=bounded_read), \
                patch.object(ETL.json, "loads", side_effect=AssertionError("must not parse oversized snapshot")):
            with self.assertRaises(ValueError):
                ETL.load(self.audit_path, self.database, max_audit_bytes=limit)
        self.assertTrue(requested)
        self.assertTrue(all(0 < size <= 64 * 1024 for size in requested))
        self.assertEqual(sum(returned), limit + 1)
        self.assert_no_output(payload)

    def test_cli_explicit_limits_accept_exact_boundaries(self):
        payload = self.write(suffix=b"\n")
        run = self.cli("--max-audit-bytes", str(len(payload)), "--max-records", "4")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["raw_records"], 4)
        self.assertEqual(self.audit_path.read_bytes(), payload)

    def test_cli_byte_record_and_override_limits_leave_no_output_or_source_change(self):
        failed = audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=2))
        for document, flags in (
            (self.document, ("--max-records", "3")),
            (failed, ("--max-records", "3", "--allow-failed-quality-gate")),
        ):
            with self.subTest(flags=flags):
                payload = self.write(document)
                self.assert_cli_rejected(self.cli(*flags))
                self.assert_no_output(payload)
        payload = self.write(suffix=b"\n \t\n")
        self.assert_cli_rejected(self.cli("--max-audit-bytes", str(len(payload) - 1)))
        self.assert_no_output(payload)

    def test_cli_invalid_limits_fail_before_opening_a_nonexistent_source(self):
        for flag in ("--max-audit-bytes", "--max-records"):
            for value in ("0", "-1", "1.5", str(2**63)):
                with self.subTest(flag=flag, value=value):
                    run = self.cli(flag, value)
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertNotIn("Traceback", run.stderr)
                    self.assertNotIn("No such file", run.stderr)
                    self.assertEqual(run.stdout, "")
                    self.assertFalse(self.audit_path.exists())
                    self.assertFalse(self.database.parent.exists())

    def test_cli_malformed_utf8_exits_cleanly_before_output_creation(self):
        payload = b'{"provider_note":"\xff"}'
        self.audit_path.write_bytes(payload)
        self.assert_cli_rejected(self.cli())
        self.assert_no_output(payload)

    def test_directory_and_device_inputs_are_rejected_as_nonregular_files(self):
        sources = [self.parent]
        device = Path("/dev/null")
        if device.exists() and not stat.S_ISREG(device.stat().st_mode):
            sources.append(device)
        for source in sources:
            with self.subTest(source=source):
                run = self.cli(audit_path=source)
                self.assert_cli_rejected(run)
                self.assertIn("regular", run.stderr.lower())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO inputs are unavailable on this platform")
    def test_fifo_input_is_rejected_without_waiting_for_a_writer(self):
        fifo = self.parent / "audit.fifo"
        os.mkfifo(fifo)
        self.assertTrue(stat.S_ISFIFO(fifo.stat().st_mode))
        self.assert_cli_rejected(run := self.cli(audit_path=fifo))
        self.assertIn("regular", run.stderr.lower())
        self.assertTrue(stat.S_ISFIFO(fifo.stat().st_mode))

    @unittest.skipUnless(hasattr(os, "symlink"), "Symbolic links are unavailable on this platform")
    def test_symlink_to_regular_audit_file_is_supported(self):
        payload = self.write()
        source = self.parent / "linked-audit.json"
        source.symlink_to(self.audit_path.name)
        result = ETL.load(source, self.database, max_audit_bytes=len(payload), max_records=4)
        self.assertEqual(result["raw_records"], 4)
        self.assertTrue(source.is_symlink())
        self.assertEqual(source.read_bytes(), payload)
        self.assertEqual(self.audit_path.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
