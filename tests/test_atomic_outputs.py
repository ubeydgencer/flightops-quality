import contextlib
import copy
import importlib.util
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flightops_quality import cli
from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.batch import analyze_results
from flightops_quality.gates import QualityPolicy
from flightops_quality.reporting import audit_document
from test_canonical import valid_row

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("atomic_etl", ROOT / "examples/etl_sqlite.py")
ETL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ETL)
ARTIFACTS = {"audit.json", "audit.html", "accepted.jsonl", "quarantined.jsonl", "duplicates.jsonl"}


class AtomicOutputTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.parent = Path(self.folder.name)
        self.output = self.parent / "audit"
        self.args = [str(ROOT / "examples/synthetic_flights.csv"), "--output", str(self.output)]

    def run_cli(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(self.args)

    def assert_cli_failure_clean(self):
        with self.assertRaises(SystemExit) as exc:
            self.run_cli()
        self.assertEqual(exc.exception.code, 2)
        self.assertFalse(os.path.lexists(self.output))
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_html_failure_leaves_no_output_and_retry_succeeds(self):
        with patch.object(cli, "render_html", side_effect=OSError("injected HTML write failure")):
            self.assert_cli_failure_clean()
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual({p.name for p in self.output.iterdir()}, ARTIFACTS)

    def test_jsonl_failure_leaves_no_output_and_retry_succeeds(self):
        original = cli._private_text_file
        def fail_jsonl(path):
            if path.name == "accepted.jsonl":
                raise OSError("injected JSONL write failure")
            return original(path)
        with patch.object(cli, "_private_text_file", side_effect=fail_jsonl):
            self.assert_cli_failure_clean()
        self.assertEqual(self.run_cli(), 0)

    def test_successful_audit_has_private_permissions(self):
        self.assertEqual(self.run_cli(), 0)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
            for artifact in self.output.iterdir():
                self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)

    def test_existing_empty_directory_is_preserved(self):
        self.output.mkdir()
        inode = self.output.stat().st_ino
        with self.assertRaises(SystemExit):
            self.run_cli()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.output.stat().st_ino, inode)

    def test_dangling_symlink_is_preserved(self):
        self.output.symlink_to(self.parent / "absent", target_is_directory=True)
        with self.assertRaises(SystemExit):
            self.run_cli()
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(os.readlink(self.output), str(self.parent / "absent"))
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_destination_created_after_validation_is_never_replaced(self):
        original = cli._publish_directory
        inode = []
        def collide(staging, destination):
            destination.mkdir()
            inode.append(destination.stat().st_ino)
            original(staging, destination)
        with patch.object(cli, "_publish_directory", side_effect=collide):
            with self.assertRaises(SystemExit) as exc:
                self.run_cli()
        self.assertEqual(exc.exception.code, 2)
        self.assertEqual(self.output.stat().st_ino, inode[0])
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_dangling_symlink_created_during_publication_is_preserved(self):
        original = cli._publish_directory
        def collide(staging, destination):
            destination.symlink_to(self.parent / "absent", target_is_directory=True)
            original(staging, destination)
        with patch.object(cli, "_publish_directory", side_effect=collide):
            with self.assertRaises(SystemExit):
                self.run_cli()
        self.assertTrue(self.output.is_symlink())
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_unavailable_native_publication_fails_closed(self):
        with patch.object(cli.sys, "platform", "unsupported"):
            self.assert_cli_failure_clean()


class AtomicWarehouseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.parent = Path(self.folder.name)
        self.audit_path = self.parent / "audit.json"
        self.database = self.parent / "warehouse.db"
        records = [normalize_record({**valid_row(), "record_id": str(i)}) for i in (1, 2)]
        self.report = analyze_results(records)
        self.document = audit_document(self.report)
        self.write_document(self.document)

    def write_document(self, document):
        self.audit_path.write_text(json.dumps(document), encoding="utf-8")

    def assert_no_database(self):
        self.assertFalse(os.path.lexists(self.database))
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_repeated_source_row_numbers_load_with_distinct_lineage(self):
        result = ETL.load(self.audit_path, self.database)
        self.assertEqual(result["raw_records"], 2)
        self.assertEqual(result["quality_gate_status"], "not_configured")
        with sqlite3.connect(self.database) as con:
            self.assertEqual(con.execute("SELECT audit_record_id, row_number FROM raw_records ORDER BY audit_record_id").fetchall(),
                             [(1, 1), (2, 1)])
            lineage = con.execute("""SELECT f.record_id, r.row_number, f.service_date,
                                      f.carrier, f.flight_number, f.provenance_json
                                      FROM flights f JOIN raw_records r USING (audit_record_id)
                                      ORDER BY f.record_id""").fetchall()
            self.assertEqual(len(lineage), 2)
            for row in lineage:
                flight = self.document["accepted"][int(row[0]) - 1]["flight"]
                self.assertEqual(row[1:5], (1, flight["service_date"], flight["carrier"], flight["flight_number"]))
                self.assertEqual(json.loads(row[5]), flight["provenance"])
            metadata = con.execute("SELECT * FROM audit_metadata").fetchone()
            self.assertEqual(metadata[:4], (self.document["package_version"], self.document["ruleset_version"],
                                           "not_configured", 0))
            self.assertEqual(json.loads(metadata[4]), self.document["quality_gate"])
            self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.database.stat().st_mode), 0o600)

    def test_insert_failure_leaves_no_database_and_retry_succeeds(self):
        original = sqlite3.connect
        class FailInsert(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.lstrip().startswith("INSERT INTO flights"):
                    raise sqlite3.OperationalError("injected insert failure")
                return super().execute(sql, parameters)
        def connect(*args, **kwargs):
            return original(*args, factory=FailInsert, **kwargs)
        with patch.object(ETL.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError):
                ETL.load(self.audit_path, self.database)
        self.assert_no_database()
        self.assertEqual(ETL.load(self.audit_path, self.database)["raw_records"], 2)

    def test_query_execution_failure_leaves_no_database(self):
        original = Path.read_text
        def broken_query(path, *args, **kwargs):
            if path.name == "route_metrics.sql":
                return "SELECT nonexistent_column FROM flights"
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", broken_query):
            with self.assertRaises(sqlite3.OperationalError):
                ETL.load(self.audit_path, self.database)
        self.assert_no_database()

    def test_existing_database_and_symlink_are_preserved(self):
        self.database.write_bytes(b"previous warehouse")
        with self.assertRaises(ValueError):
            ETL.load(self.audit_path, self.database)
        self.assertEqual(self.database.read_bytes(), b"previous warehouse")
        self.database.unlink()
        self.database.symlink_to(self.parent / "absent")
        with self.assertRaises(ValueError):
            ETL.load(self.audit_path, self.database)
        self.assertTrue(self.database.is_symlink())

    def test_concurrent_destination_is_never_replaced(self):
        original = os.link
        def collide(source, destination, **kwargs):
            Path(destination).write_bytes(b"concurrent warehouse")
            return original(source, destination, **kwargs)
        with patch.object(ETL.os, "link", side_effect=collide):
            with self.assertRaises(FileExistsError):
                ETL.load(self.audit_path, self.database)
        self.assertEqual(self.database.read_bytes(), b"concurrent warehouse")
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_failed_quality_gate_rejects_before_creating_database(self):
        self.write_document(audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=3)))
        with self.assertRaisesRegex(ValueError, "quality gate failed"):
            ETL.load(self.audit_path, self.database)
        self.assert_no_database()

    def test_failed_gate_explicit_override_remains_in_metadata(self):
        document = audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=3))
        self.write_document(document)
        result = ETL.load(self.audit_path, self.database, allow_failed_quality_gate=True)
        self.assertEqual(result["quality_gate_status"], "failed")
        self.assertIs(result["quality_gate_override"], True)
        with sqlite3.connect(self.database) as con:
            metadata = con.execute("SELECT quality_gate_status, quality_gate_override, quality_gate_json FROM audit_metadata").fetchone()
        self.assertEqual(metadata[:2], ("failed", 1))
        self.assertEqual(json.loads(metadata[2]), document["quality_gate"])

    def test_override_requires_a_boolean(self):
        for value in (1, "true", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ETL.load(self.audit_path, self.database, allow_failed_quality_gate=value)
                self.assert_no_database()

    def test_unknown_malformed_and_contradictory_gates_are_rejected(self):
        gates = [None, "passed", {}, {"status": "unknown"}, {"status": []}, {"status": "passed"}]
        failed = audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=3))["quality_gate"]
        contradictory = copy.deepcopy(failed)
        contradictory["status"] = "passed"
        gates.append(contradictory)
        for gate in gates:
            with self.subTest(gate=gate):
                self.write_document({**self.document, "quality_gate": gate})
                with self.assertRaises(ValueError):
                    ETL.load(self.audit_path, self.database, allow_failed_quality_gate=True)
                self.assert_no_database()

    def test_passed_and_legacy_gates_load_without_override(self):
        passed = audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=2))
        self.write_document(passed)
        self.assertEqual(ETL.load(self.audit_path, self.database)["quality_gate_status"], "passed")
        self.database.unlink()
        legacy = dict(self.document)
        legacy.pop("quality_gate")
        self.write_document(legacy)
        result = ETL.load(self.audit_path, self.database)
        self.assertEqual(result["quality_gate_status"], "legacy")
        self.assertIs(result["quality_gate_override"], False)

    def test_forged_gate_cannot_claim_coverage_absent_from_records(self):
        report = analyze_results([normalize_record({**valid_row(), "aibt": None})])
        document = audit_document(report, quality_policy=QualityPolicy(min_arrival_coverage_percent=80))
        self.assertEqual(document["quality_gate"]["measurements"]["arrival_coverage_percent"]["value"], 0)
        forged = copy.deepcopy(document)
        gate = forged["quality_gate"]
        gate["status"] = "passed"
        gate["measurements"]["arrival_coverage_percent"].update(value=100, numerator=1, denominator=1)
        gate["measurements"]["otp_eligible_flights"]["value"] = 1
        gate["checks"][0].update(observed=100, passed=True,
                                 reason="Observed value satisfies the inclusive threshold.")
        self.write_document(forged)
        for override in (False, True):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, "contradicts its records"):
                    ETL.load(self.audit_path, self.database, allow_failed_quality_gate=override)
                self.assert_no_database()

    def test_forged_gate_cannot_change_quarantine_population(self):
        document = audit_document(self.report, quality_policy=QualityPolicy(max_quarantine_rate_percent=20))
        gate = document["quality_gate"]
        gate["status"] = "failed"
        gate["measurements"]["quarantine_rate_percent"].update(value=100 / 3, numerator=1, denominator=3)
        gate["checks"][0].update(observed=100 / 3, passed=False,
                                 reason="Observed value does not satisfy the inclusive threshold.")
        self.write_document(document)
        with self.assertRaisesRegex(ValueError, "contradicts its records"):
            ETL.load(self.audit_path, self.database, allow_failed_quality_gate=True)
        self.assert_no_database()

    def test_gate_booleans_cannot_replace_numeric_measurements(self):
        document = copy.deepcopy(self.document)
        document["quality_gate"]["measurements"]["quarantine_rate_percent"]["numerator"] = False
        self.write_document(document)
        with self.assertRaisesRegex(ValueError, "contradicts its records"):
            ETL.load(self.audit_path, self.database, allow_failed_quality_gate=True)
        self.assert_no_database()

    def test_stored_metrics_and_status_must_match_normalized_flight(self):
        for change in ("delay", "bool_metric", "nonfinite", "flag", "naive", "missing_time"):
            with self.subTest(change=change):
                document = copy.deepcopy(self.document)
                record = document["accepted"][0]
                if change == "delay":
                    record["metrics"]["arrival_delay_minutes"] = 999
                elif change == "bool_metric":
                    record["metrics"]["arrival_delay_minutes"] = False
                elif change == "nonfinite":
                    record["metrics"]["arrival_delay_minutes"] = float("nan")
                elif change == "flag":
                    record["flight"]["cancelled"] = "false"
                elif change == "naive":
                    record["flight"]["sibt"] = record["flight"]["sibt"].split("+")[0]
                else:
                    record["flight"].pop("aibt")
                self.write_document(document)
                with self.assertRaises(ValueError):
                    ETL.load(self.audit_path, self.database, allow_failed_quality_gate=True)
                self.assert_no_database()

    def test_etl_cli_failed_gate_reports_clean_error_and_explicit_override(self):
        self.write_document(audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=3)))
        command = [sys.executable, str(ROOT / "examples/etl_sqlite.py"), str(self.audit_path), str(self.database)]
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("Audit quality gate failed", run.stderr)
        self.assertNotIn("Traceback", run.stderr)
        self.assert_no_database()
        allowed = subprocess.run(command + ["--allow-failed-quality-gate"], capture_output=True, text=True)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIs(json.loads(allowed.stdout)["quality_gate_override"], True)


if __name__ == "__main__":
    unittest.main()
