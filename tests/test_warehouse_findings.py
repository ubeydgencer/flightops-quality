import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.batch import analyze_results
from flightops_quality.models import Issue
from flightops_quality.reporting import audit_document
from test_canonical import valid_row

ROOT = Path(__file__).resolve().parents[1]


def load_example(name, filename):
    specification = importlib.util.spec_from_file_location(name, ROOT / "examples" / filename)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


ETL = load_example("findings_etl", "etl_sqlite.py")
FINDINGS = load_example("warehouse_findings", "warehouse_findings.py")


class WarehouseFindingsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.parent = Path(folder.name)
        self.database = self.parent / "warehouse.db"
        first = {**valid_row(), "record_id": "first"}
        second = {**first, "record_id": "clean"}
        quarantined = {**first, "record_id": "quarantined", "aibt": "2026-10-09T04:00:00Z"}
        # API-produced audits permit repeated source positions. Internal audit
        # IDs, rather than these positions, distinguish affected observations.
        report = analyze_results(normalize_record(row, row_number=7)
                                 for row in (first, second, quarantined, first))
        self.assertEqual(report.counts,
                         {"input": 4, "accepted": 2, "quarantined": 1, "duplicates": 1})
        warning = Issue("SHARED_CODE", "warning", ("provider",), "Provider warning")
        information = Issue("SHARED_CODE", "info", ("provider",), "Provider note")
        unicode_note = Issue('İstanbul "not" ? & #', "info", ("provider",), "Kaynak uçuş notu")
        sql_note = Issue("'); DROP TABLE raw_records;--", "info", (), "Literal provider code")
        accepted = replace(report.accepted[0], issues=report.accepted[0].issues
                           + (warning, warning, information, unicode_note, unicode_note, sql_note))
        quarantine = replace(report.quarantined[0], issues=report.quarantined[0].issues
                             + (warning, warning))
        duplicate = replace(report.duplicates[0], issues=report.duplicates[0].issues
                            + (information, information, information))
        self.report = replace(report, accepted=(accepted, report.accepted[1]),
                              quarantined=(quarantine,), duplicates=(duplicate,))
        self.document = self.load_report(self.report)

    def load_report(self, report, database=None):
        document = audit_document(report)
        audit = self.parent / "audit.json"
        audit.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        ETL.load(audit, database or self.database)
        return document

    def digest(self, database=None):
        return hashlib.sha256((database or self.database).read_bytes()).hexdigest()

    def stored_records(self):
        with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute(
                "SELECT audit_record_id, disposition, issues_json FROM raw_records"
            ).fetchall()
        return [(record_id, disposition, json.loads(issues))
                for record_id, disposition, issues in rows]

    def expected_analysis(self):
        records = self.stored_records()
        occurrences = Counter()
        affected = defaultdict(set)
        categories = defaultdict(lambda: defaultdict(set))
        globally_affected = set()
        for record_id, disposition, issues in records:
            for issue in issues:
                key = issue["code"], issue["severity"]
                occurrences[key] += 1
                affected[key].add(record_id)
                categories[key][disposition].add(record_id)
                globally_affected.add(record_id)
        findings = []
        for code, severity in sorted(occurrences):
            key = code, severity
            findings.append({
                "code": code, "severity": severity, "occurrences": occurrences[key],
                "affected_records": len(affected[key]),
                "affected_accepted_records": len(categories[key]["accepted"]),
                "affected_quarantined_records": len(categories[key]["quarantined"]),
                "affected_duplicate_records": len(categories[key]["duplicates"]),
            })
        return {
            "raw_records": len(records), "records_with_findings": len(globally_affected),
            "records_without_findings": len(records) - len(globally_affected),
            "finding_occurrences": sum(occurrences.values()), "findings": findings,
        }

    def cli(self, database):
        return subprocess.run(
            [sys.executable, str(ROOT / "examples/warehouse_findings.py"), str(database)],
            capture_output=True, text=True, cwd=ROOT, timeout=10,
        )

    def test_repeated_codes_severities_and_dispositions_match_independent_record_sets(self):
        previous = self.digest()
        result = FINDINGS.analyze(self.database)
        self.assertEqual(result, self.expected_analysis())
        groups = {(row["code"], row["severity"]): row for row in result["findings"]}
        warning = groups["SHARED_CODE", "warning"]
        self.assertEqual((warning["occurrences"], warning["affected_records"],
                          warning["affected_accepted_records"],
                          warning["affected_quarantined_records"],
                          warning["affected_duplicate_records"]), (4, 2, 1, 1, 0))
        information = groups["SHARED_CODE", "info"]
        self.assertEqual((information["occurrences"], information["affected_records"],
                          information["affected_accepted_records"],
                          information["affected_quarantined_records"],
                          information["affected_duplicate_records"]), (4, 2, 1, 0, 1))
        by_code = Counter()
        for row in result["findings"]:
            by_code[row["code"]] += row["occurrences"]
            self.assertEqual(row["affected_records"], row["affected_accepted_records"]
                             + row["affected_quarantined_records"]
                             + row["affected_duplicate_records"])
        self.assertEqual(dict(by_code), self.document["summary"]["issue_counts"])
        self.assertEqual(self.digest(), previous)

    def test_global_affected_records_are_not_the_sum_of_group_counts(self):
        result = FINDINGS.analyze(self.database)
        self.assertEqual(result["raw_records"], 4)
        self.assertEqual(result["records_with_findings"], 3)
        self.assertEqual(result["records_without_findings"], 1)
        self.assertGreater(sum(row["affected_records"] for row in result["findings"]),
                           result["records_with_findings"])
        self.assertEqual(result["finding_occurrences"],
                         sum(row["occurrences"] for row in result["findings"]))

    def test_standalone_sql_returns_the_same_groups_without_flights_join(self):
        query = (ROOT / "examples/warehouse_findings.sql").read_text(encoding="utf-8")
        previous = self.digest()
        with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(query)]
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM flights").fetchone()[0], 2)
        self.assertEqual(rows, self.expected_analysis()["findings"])
        self.assertTrue(any(row["affected_quarantined_records"] for row in rows))
        self.assertTrue(any(row["affected_duplicate_records"] for row in rows))
        self.assertEqual(self.digest(), previous)

    def test_empty_batch_has_explicit_zero_totals_and_no_fictitious_finding(self):
        database = self.parent / "empty.db"
        self.load_report(analyze_results([]), database)
        previous = self.digest(database)
        self.assertEqual(FINDINGS.analyze(database), {
            "raw_records": 0, "records_with_findings": 0, "records_without_findings": 0,
            "finding_occurrences": 0, "findings": [],
        })
        self.assertEqual(self.digest(database), previous)

    def test_clean_nonempty_batch_retains_records_without_findings(self):
        database = self.parent / "clean.db"
        clean = analyze_results([normalize_record({**valid_row(), "record_id": "clean"})])
        self.assertEqual(clean.accepted[0].issues, ())
        self.load_report(clean, database)
        self.assertEqual(FINDINGS.analyze(database), {
            "raw_records": 1, "records_with_findings": 0, "records_without_findings": 1,
            "finding_occurrences": 0, "findings": [],
        })

    def test_cli_special_filename_preserves_unicode_and_closed_database_bytes(self):
        query_character = " ?" if os.name != "nt" else ""
        database = self.parent / f"İstanbul #{query_character} & mode=rw uçuş.db"
        os.rename(self.database, database)
        previous = self.digest(database)
        before_files = {path.name for path in self.parent.iterdir()}
        run = self.cli(database)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, "")
        result = json.loads(run.stdout)
        self.assertEqual(result, FINDINGS.analyze(database))
        self.assertTrue(any(row["code"] == 'İstanbul "not" ? & #'
                            for row in result["findings"]))
        self.assertEqual(self.digest(database), previous)
        self.assertEqual({path.name for path in self.parent.iterdir()}, before_files)

    def test_missing_directory_and_wrong_schema_fail_without_creating_files(self):
        missing = self.parent / "missing-parent" / "missing.db"
        wrong = self.parent / "wrong.db"
        with closing(sqlite3.connect(wrong)) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.commit()
        before_files = {path.name for path in self.parent.iterdir()}
        previous = self.digest()
        wrong_previous = self.digest(wrong)
        for database in (missing, self.parent, wrong):
            with self.subTest(database=database.name):
                with self.assertRaises((ValueError, OSError, sqlite3.Error)):
                    FINDINGS.analyze(database)
                run = self.cli(database)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertEqual(run.stdout, "")
                self.assertIn("warehouse_findings:", run.stderr)
                self.assertNotIn("Traceback", run.stderr)
        self.assertEqual({path.name for path in self.parent.iterdir()}, before_files)
        self.assertFalse(missing.parent.exists())
        self.assertEqual(self.digest(), previous)
        self.assertEqual(self.digest(wrong), wrong_previous)

    def test_missing_json_capability_fails_clearly_without_changing_database(self):
        previous = self.digest()
        original_connect = sqlite3.connect

        class MissingJSON(sqlite3.Connection):
            def execute(self, query, *args, **kwargs):
                if "json_each" in query.lower() or "json_extract" in query.lower():
                    raise sqlite3.OperationalError("no such table: json_each")
                return super().execute(query, *args, **kwargs)

        def connect(*args, **kwargs):
            kwargs["factory"] = MissingJSON
            return original_connect(*args, **kwargs)

        with patch.object(FINDINGS.sqlite3, "connect", side_effect=connect):
            with self.assertRaisesRegex(ValueError, "SQLite.*JSON"):
                FINDINGS.analyze(self.database)
        self.assertEqual(self.digest(), previous)

    def test_write_query_is_rejected_by_read_only_connection(self):
        previous = self.digest()
        original_read = Path.read_text

        def changed_query(path, *args, **kwargs):
            if path.name == "warehouse_findings.sql":
                return "DELETE FROM raw_records"
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", changed_query):
            with self.assertRaises(sqlite3.Error):
                FINDINGS.analyze(self.database)
        self.assertEqual(self.digest(), previous)
        self.assertEqual(len(self.stored_records()), 4)


if __name__ == "__main__":
    unittest.main()
