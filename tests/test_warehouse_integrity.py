import copy
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flightops_quality.adapters.canonical import normalize_record
from flightops_quality.batch import analyze_results
from flightops_quality.gates import QualityPolicy
from flightops_quality.reporting import audit_document
from test_canonical import valid_row

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("warehouse_integrity_etl", ROOT / "examples/etl_sqlite.py")
ETL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ETL)


def raw_digest(raw):
    payload = json.dumps(raw, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def reverse_mapping_order(value):
    if isinstance(value, dict):
        return {key: reverse_mapping_order(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reverse_mapping_order(item) for item in value]
    return value


class WarehouseIntegrityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.parent = Path(folder.name)
        self.audit_path = self.parent / "audit.json"
        self.database = self.parent / "new-output" / "warehouse.db"
        first = {**valid_row(), "record_id": "first",
                 "context": {"city": "İstanbul", "sequence": [1, True, None, {"label": "uçuş"}]}}
        second = {**first, "record_id": "second", "flight_number": "200"}
        quarantined = {**first, "record_id": "quarantined", "aibt": "2026-10-09T04:00:00Z"}
        self.report = analyze_results(normalize_record(row, row_number=number)
                                      for number, row in enumerate((first, second, quarantined, first), start=11))
        self.assertEqual(self.report.counts, {"input": 4, "accepted": 2, "quarantined": 1, "duplicates": 1})
        self.document = audit_document(
            self.report, {"nested": {"label": "source-label"}},
            quality_policy=QualityPolicy(min_otp_eligible_flights=2),
        )
        self.assertEqual(self.document["quality_gate"]["status"], "passed")

    def write_document(self, document):
        payload = json.dumps(document, ensure_ascii=True).encode("utf-8")
        self.audit_path.write_bytes(payload)
        return payload

    def assert_rejected_before_loading(self, *, override=False):
        payload = self.audit_path.read_bytes()
        with self.assertRaises(ValueError):
            ETL.load(self.audit_path, self.database, allow_failed_quality_gate=override)
        self.assertFalse(os.path.lexists(self.database))
        self.assertFalse(self.database.parent.exists())
        self.assertEqual({path.name for path in self.parent.iterdir()}, {self.audit_path.name})
        self.assertEqual(self.audit_path.read_bytes(), payload)

    def test_changed_raw_in_every_disposition_is_rejected_even_with_failed_gate_override(self):
        failed = audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=3))
        self.assertEqual(failed["quality_gate"]["status"], "failed")
        for category in ("accepted", "quarantined", "duplicates"):
            for override in (False, True):
                with self.subTest(category=category, failed_gate_override=override):
                    document = copy.deepcopy(failed if override else self.document)
                    record = document[category][0]
                    original_digest = record["raw_sha256"]
                    record["raw"]["context"]["city"] = "changed after audit creation"
                    self.assertNotEqual(raw_digest(record["raw"]), original_digest)
                    self.write_document(document)
                    self.assert_rejected_before_loading(override=override)

    def test_missing_malformed_and_wrong_digests_are_rejected(self):
        for category in ("accepted", "quarantined", "duplicates"):
            for digest in ("missing", None, 123, "g" * 64, "0" * 64, "ab" * 31):
                with self.subTest(category=category, digest=digest):
                    document = copy.deepcopy(self.document)
                    record = document[category][0]
                    if digest == "missing":
                        record.pop("raw_sha256")
                    else:
                        record["raw_sha256"] = digest
                    self.write_document(document)
                    self.assert_rejected_before_loading()

    def test_raw_requires_a_bounded_utf8_json_mapping_not_merely_a_matching_digest(self):
        nested = "leaf"
        for _ in range(40):
            nested = {"child": nested}
        invalid_values = (None, [], "not a mapping", 42, {"deep": nested},
                          {"too_large": 1 << 5000}, {"value": "\ud800"}, {"\ud800": "value"})
        for raw in invalid_values:
            with self.subTest(raw_type=type(raw).__name__, invalid_utf8=isinstance(raw, dict) and len(raw) == 1):
                document = copy.deepcopy(self.document)
                record = document["quarantined"][0]
                record["raw"] = raw
                try:
                    record["raw_sha256"] = raw_digest(raw)
                except UnicodeEncodeError:
                    # An escaped surrogate is valid JSON syntax but has no valid
                    # canonical UTF-8 byte representation to hash or retain.
                    record["raw_sha256"] = "0" * 64
                self.write_document(document)
                self.assert_rejected_before_loading()

    def test_duplicate_json_keys_are_rejected_throughout_the_document(self):
        payload = json.dumps(self.document, ensure_ascii=False, separators=(",", ":"))
        replacements = (
            ('"counts":', '"counts":{},"counts":'),
            ('"row_number":11,', '"row_number":999,"row_number":11,'),
            ('"label":"uçuş"', '"label":"discarded","label":"uçuş"'),
            ('"label":"source-label"', '"label":"discarded","label":"source-label"'),
        )
        for original, duplicate in replacements:
            with self.subTest(target=original):
                self.assertIn(original, payload)
                changed = payload.replace(original, duplicate, 1)
                # Last-key-wins decoding hides the ambiguity and leaves every
                # parsed record/digest/gate valid; the loader must reject syntax.
                self.assertEqual(json.loads(changed), self.document)
                self.audit_path.write_bytes(changed.encode("utf-8"))
                self.assert_rejected_before_loading()

    def test_unicode_nested_raw_and_reordered_json_preserve_warehouse_byte_lineage(self):
        document = reverse_mapping_order(copy.deepcopy(self.document))
        document["accepted"].reverse()
        payload = json.dumps(document, ensure_ascii=False, indent=1).encode("utf-8")
        self.audit_path.write_bytes(payload)
        result = ETL.load(self.audit_path, self.database)
        self.assertEqual((result["raw_records"], result["quality_gate_status"]), (4, "passed"))
        expected = [(category, record) for category in ("accepted", "quarantined", "duplicates")
                    for record in document[category]]
        with sqlite3.connect(self.database) as connection:
            stored = connection.execute(
                "SELECT disposition, row_number, raw_sha256, raw_json FROM raw_records ORDER BY audit_record_id"
            ).fetchall()
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT count(*) FROM flights").fetchone()[0], 2)
        self.assertEqual(len(stored), len(expected))
        for (disposition, row_number, digest, raw_json), (category, record) in zip(stored, expected):
            self.assertEqual((disposition, row_number), (category, record["row_number"]))
            self.assertEqual(json.loads(raw_json), record["raw"])
            self.assertIn("İstanbul", raw_json)
            self.assertIn("uçuş", raw_json)
            self.assertEqual(digest, record["raw_sha256"])
            self.assertEqual(digest, raw_digest(json.loads(raw_json)))
        self.assertEqual(self.audit_path.read_bytes(), payload)

    def test_cli_rejects_raw_integrity_and_duplicate_key_failures_without_traceback_or_output(self):
        failed = audit_document(self.report, quality_policy=QualityPolicy(min_otp_eligible_flights=3))
        failed["duplicates"][0]["raw"]["context"]["city"] = "changed after audit creation"
        malformed_digest = json.dumps(failed).encode("utf-8")
        duplicate_key = json.dumps(self.document).replace('"counts":', '"counts": {}, "counts":', 1).encode("utf-8")
        for payload, flags in ((malformed_digest, ["--allow-failed-quality-gate"]), (duplicate_key, [])):
            with self.subTest(override=bool(flags)):
                self.audit_path.write_bytes(payload)
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
