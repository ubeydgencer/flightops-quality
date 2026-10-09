import copy
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.batch import analyze_results
from flightops_quality.gates import QualityPolicy
from flightops_quality.models import Issue
from flightops_quality.reporting import audit_document
from test_canonical import valid_row

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("warehouse_summary_etl", ROOT / "examples/etl_sqlite.py")
ETL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ETL)


def reordered(value):
    if isinstance(value, dict):
        return {key: reordered(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reordered(item) for item in value]
    return value


class WarehouseSummaryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.parent = Path(folder.name)
        self.audit_path = self.parent / "audit.json"
        self.database = self.parent / "new-output" / "warehouse.db"
        observed = {**valid_row(), "record_id": "observed", "provider_note": "İstanbul uçuşu"}
        missing = {**observed, "record_id": "missing-arrival", "aibt": None}
        invalid = {**observed, "record_id": "quarantined", "aibt": "2026-10-09T04:00:00Z"}
        report = analyze_results(normalize_record(row, row_number=number)
                                 for number, row in enumerate((observed, missing, invalid, observed), start=11))

        def recorded_findings(records):
            return tuple(replace(record, issues=tuple(
                replace(issue, message=f"Kaynak İstanbul: {issue.message}") for issue in record.issues
            )) for record in records)

        self.report = replace(report, accepted=recorded_findings(report.accepted),
                              quarantined=recorded_findings(report.quarantined),
                              duplicates=recorded_findings(report.duplicates))
        self.document = audit_document(self.report, quality_policy=QualityPolicy(
            min_arrival_coverage_percent=50, min_otp_eligible_flights=1,
        ))
        self.assertEqual(self.document["quality_gate"]["status"], "passed")
        self.assertEqual(self.document["summary"]["issue_counts"],
                         {"ACTUAL_INCOMPLETE": 1, "ACTUAL_ORDER": 1, "DUPLICATE_EXACT": 1})

    def write(self, document):
        payload = json.dumps(document, ensure_ascii=False, indent=1).encode("utf-8")
        self.audit_path.write_bytes(payload)
        return payload

    def assert_rejected_before_loading(self, *, override=False):
        original = self.audit_path.read_bytes()
        with self.assertRaises(ValueError):
            ETL.load(self.audit_path, self.database, allow_failed_quality_gate=override)
        self.assertFalse(os.path.lexists(self.database))
        self.assertFalse(self.database.parent.exists())
        self.assertEqual(self.audit_path.read_bytes(), original)
        self.assertEqual({path.name for path in self.parent.iterdir()}, {self.audit_path.name})

    def test_summary_kpi_status_counter_exclusion_policy_and_finding_tampering_is_rejected(self):
        for case in ("coverage", "otp", "status", "rate", "counts", "exclusion", "policy", "findings"):
            with self.subTest(case=case):
                document = copy.deepcopy(self.document)
                summary = document["summary"]
                arrival = summary["arrival_otp_15_completed"]
                if case == "coverage":
                    arrival.update(coverage_population=1, coverage_percent=100)
                elif case == "otp":
                    arrival.update(on_time=0, late=1, percent=0)
                elif case == "status":
                    summary["accepted_population"]["cancelled"] = 1
                elif case == "rate":
                    summary["accepted_population"]["diversion_rate_percent"] = 100
                elif case == "counts":
                    summary["counts"]["accepted"] = 99
                elif case == "exclusion":
                    arrival["excluded_missing_arrival_delay"] = 0
                elif case == "policy":
                    arrival["policy"] = "delay <= 15 minutes"
                else:
                    summary["issue_counts"] = {}
                self.write(document)
                self.assert_rejected_before_loading()

    def test_summary_booleans_null_missing_and_extra_fields_do_not_match_expected_values(self):
        for case in ("boolean_one", "boolean_zero", "null_percent", "missing_policy", "extra_field", "missing_summary"):
            with self.subTest(case=case):
                document = copy.deepcopy(self.document)
                summary = document["summary"]
                if case == "boolean_one":
                    summary["issue_counts"]["ACTUAL_INCOMPLETE"] = True
                elif case == "boolean_zero":
                    summary["accepted_population"]["cancelled"] = False
                elif case == "null_percent":
                    summary["arrival_otp_15_completed"]["percent"] = None
                elif case == "missing_policy":
                    summary["arrival_otp_15_completed"].pop("policy")
                elif case == "extra_field":
                    summary["unverified_extension"] = {"eligible": 999}
                else:
                    document.pop("summary")
                self.write(document)
                self.assert_rejected_before_loading()

    def test_recorded_unicode_findings_from_all_categories_and_reordered_valid_summary_are_preserved(self):
        provider_note = Issue("PROVIDER_NOTE", "info", ("provider_note",), "Kaynak İstanbul: sağlayıcı uçuş notu")
        annotated = self.report.accepted[1]
        annotated = replace(annotated, issues=(provider_note, *annotated.issues, provider_note, provider_note))
        report = replace(self.report, accepted=(self.report.accepted[0], annotated))
        document = audit_document(report, quality_policy=QualityPolicy(**self.document["quality_gate"]["policy"]))
        self.assertEqual(document["summary"]["issue_counts"]["PROVIDER_NOTE"], 3)
        document = reordered(document)
        document["accepted"].reverse()
        payload = self.write(document)
        result = ETL.load(self.audit_path, self.database)
        self.assertEqual((result["raw_records"], result["quality_gate_status"]), (4, "passed"))
        self.assertEqual(result["routes"][0]["arrival_coverage_population"], 2)
        self.assertEqual(result["routes"][0]["arrival_delay_coverage_percent"], 50)
        with sqlite3.connect(self.database) as connection:
            stored_summary = json.loads(connection.execute("SELECT summary_json FROM audit_metadata").fetchone()[0])
            stored_findings = connection.execute("SELECT disposition, issues_json FROM raw_records ORDER BY audit_record_id").fetchall()
        self.assertEqual(stored_summary, document["summary"])
        self.assertEqual(stored_summary["issue_counts"]["PROVIDER_NOTE"], 3)
        expected_findings = [(category, record["issues"])
                             for category in ("accepted", "quarantined", "duplicates") for record in document[category]]
        self.assertEqual([(category, json.loads(issues)) for category, issues in stored_findings], expected_findings)
        self.assertTrue(all("Kaynak İstanbul" in issue["message"]
                            for _, issues in expected_findings for issue in issues))
        self.assertEqual(self.audit_path.read_bytes(), payload)

    def test_malformed_recorded_findings_in_every_category_fail_before_output_creation(self):
        valid_issue = {"code": "PROVIDER_NOTE", "severity": "info", "fields": ["note"], "message": "İstanbul"}
        malformed = (None, {}, [None], [{}],
                     [{**valid_issue, "code": 123}], [{**valid_issue, "severity": "fatal"}],
                     [{**valid_issue, "fields": "note"}], [{**valid_issue, "fields": [123]}],
                     [{**valid_issue, "message": None}],
                     [{key: value for key, value in valid_issue.items() if key != "message"}])
        for category in ("accepted", "quarantined", "duplicates"):
            for index, issues in enumerate(malformed):
                with self.subTest(category=category, malformed_case=index):
                    document = copy.deepcopy(self.document)
                    document[category][0]["issues"] = issues
                    self.write(document)
                    self.assert_rejected_before_loading()
        document = copy.deepcopy(self.document)
        document["accepted"][0]["issues"] = [{**valid_issue, "severity": "error"}]
        self.write(document)
        self.assert_rejected_before_loading()

    def test_no_gate_current_and_supported_legacy_paired_coverage_absence_load_successfully(self):
        cases = ((self.document["package_version"], False), ("0.1.0", True), ("0.1.1", True))
        for index, (version, remove_coverage) in enumerate(cases):
            with self.subTest(version=version, remove_coverage=remove_coverage):
                document = copy.deepcopy(self.document)
                document["package_version"] = version
                document.pop("quality_gate")
                if remove_coverage:
                    for field in ("coverage_population", "coverage_percent"):
                        document["summary"]["arrival_otp_15_completed"].pop(field)
                document = reordered(document)
                self.database = self.parent / f"valid-legacy-{index}" / "warehouse.db"
                payload = self.write(document)
                result = ETL.load(self.audit_path, self.database)
                self.assertEqual(result["quality_gate_status"], "legacy")
                with sqlite3.connect(self.database) as connection:
                    stored = json.loads(connection.execute("SELECT summary_json FROM audit_metadata").fetchone()[0])
                self.assertEqual(stored, document["summary"])
                self.assertEqual(self.audit_path.read_bytes(), payload)

    def test_legacy_projection_rejects_partial_coverage_unsupported_versions_gates_and_remaining_tampering(self):
        cases = (("0.1.0", False, ("coverage_population",), False),
                 ("0.1.1", False, ("coverage_percent",), False),
                 ("0.1.0", True, ("coverage_population", "coverage_percent"), False),
                 ("0.2.0", False, ("coverage_population", "coverage_percent"), False),
                 ("0.2.6", False, ("coverage_population", "coverage_percent"), False),
                 ("unknown", False, ("coverage_population", "coverage_percent"), False),
                 (None, False, ("coverage_population", "coverage_percent"), False),
                 ("0.1.1", False, ("coverage_population", "coverage_percent"), True))
        for version, keep_gate, removed, tamper in cases:
            with self.subTest(version=version, keep_gate=keep_gate, removed=removed, tamper=tamper):
                document = copy.deepcopy(self.document)
                if version is None:
                    document.pop("package_version")
                else:
                    document["package_version"] = version
                if not keep_gate:
                    document.pop("quality_gate")
                for field in removed:
                    document["summary"]["arrival_otp_15_completed"].pop(field)
                if tamper:
                    document["summary"]["issue_counts"] = {}
                self.write(document)
                self.assert_rejected_before_loading()

    def test_failed_gate_override_cannot_bypass_summary_integrity_but_valid_override_loads(self):
        failed = audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=2))
        self.assertEqual(failed["quality_gate"]["status"], "failed")
        changed = copy.deepcopy(failed)
        changed["summary"]["arrival_otp_15_completed"].update(coverage_population=1, coverage_percent=100)
        self.write(changed)
        self.assert_rejected_before_loading(override=True)
        payload = self.write(failed)
        result = ETL.load(self.audit_path, self.database, allow_failed_quality_gate=True)
        self.assertEqual(result["quality_gate_status"], "failed")
        self.assertIs(result["quality_gate_override"], True)
        with sqlite3.connect(self.database) as connection:
            summary_json, overridden = connection.execute("SELECT summary_json, quality_gate_override FROM audit_metadata").fetchone()
        self.assertEqual(json.loads(summary_json), failed["summary"])
        self.assertEqual(overridden, 1)
        self.assertEqual(self.audit_path.read_bytes(), payload)

    def test_cli_summary_and_finding_errors_exit_cleanly_without_output_or_source_changes(self):
        failed = audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=2))
        failed["summary"]["issue_counts"] = {}
        malformed = copy.deepcopy(self.document)
        malformed["quarantined"][0]["issues"][0]["fields"] = "aibt"
        for document, flags in ((failed, ["--allow-failed-quality-gate"]), (malformed, [])):
            with self.subTest(override=bool(flags)):
                payload = self.write(document)
                command = [sys.executable, str(ROOT / "examples/etl_sqlite.py"),
                           str(self.audit_path), str(self.database), *flags]
                run = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("etl_sqlite:", run.stderr)
                self.assertNotIn("Traceback", run.stderr)
                self.assertEqual(run.stdout, "")
                self.assertFalse(os.path.lexists(self.database))
                self.assertFalse(self.database.parent.exists())
                self.assertEqual(self.audit_path.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
