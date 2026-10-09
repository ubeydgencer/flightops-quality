import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from test_bts import bts_row

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bts_month_reader", ROOT / "examples/validate_bts_month.py")
READER = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(ROOT / "examples"), *sys.path]):
    SPEC.loader.exec_module(READER)

ZONES = {"JFK": "America/New_York", "LAX": "America/Los_Angeles", "ORD": "America/Chicago"}


def row(**changes):
    return {**bts_row(), "FlightDate": "2025-01-01", "OriginAirportID": "12478",
            "OriginAirportSeqID": "1247805", "DestAirportID": "12892",
            "DestAirportSeqID": "1289208", "": "", **changes}


class BtsMonthReaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.parent = Path(self.folder.name)
        self.archive = self.parent / "source.zip"
        self.output = self.parent / "validation"
        self.timezones = self.parent / "zones.json"
        self.timezones.write_text(json.dumps(ZONES), encoding="utf-8")
        self.headers = sorted(READER.REQUIRED_FIELDS) + [""]

    def write_archive(self, rows=(), *, headers=None, payload=None, extra_members=()):
        headers = self.headers if headers is None else headers
        if payload is None:
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(headers)
            for record in rows:
                writer.writerow([record.get(name, "") for name in headers])
            payload = stream.getvalue().encode("utf-8")
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.writestr("month.csv", payload)
            for name, content in extra_members:
                bundle.writestr(name, content)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest(), payload

    def read(self, digest, period="2025-01"):
        return READER.read_cohort(self.archive, digest, period, ZONES)

    def args(self, digest):
        return ["--archive", str(self.archive), "--expected-sha256", digest,
                "--period", "2025-01", "--timezones", str(self.timezones),
                "--output", str(self.output)]

    def run_main(self, digest):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return READER.main(self.args(digest))

    def assert_no_output(self):
        self.assertFalse(os.path.lexists(self.output))
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_archive_and_full_csv_hash_cover_unselected_rows(self):
        digest, payload = self.write_archive([
            row(), row(Origin="DEN", FlightDate="2025-01-31", Flight_Number_Reporting_Airline="2"),
        ])
        rows, headers, manifest = self.read(digest)
        self.assertEqual(len(rows), 1)
        self.assertEqual(headers, self.headers)
        self.assertEqual(manifest["archive_sha256"], digest)
        self.assertEqual(manifest["csv_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(manifest["csv_bytes"], len(payload))
        self.assertEqual(manifest["source_rows_scanned"], 2)
        self.assertEqual(manifest["source_date_range"], {"start": "2025-01-01", "end": "2025-01-31"})

    def test_wrong_checksum_and_invalid_checksum_format_are_rejected(self):
        self.write_archive([row()])
        for digest in ("0" * 64, "not-a-sha256"):
            with self.subTest(digest=digest):
                with self.assertRaises(ValueError):
                    self.read(digest)

    def test_wrong_date_outside_cohort_still_rejects_entire_scan(self):
        for day in ("2025-02-01", "2025-01-32", "20250101"):
            with self.subTest(day=day):
                digest, _ = self.write_archive([row(), row(Origin="DEN", FlightDate=day)])
                with self.assertRaises(ValueError):
                    self.read(digest)

    def test_duplicate_blank_and_reserved_headers_are_rejected(self):
        cases = [self.headers + ["FlightDate"], ["", *self.headers],
                 self.headers + [READER.SOURCE_LINE_FIELD]]
        for headers in cases:
            with self.subTest(headers=headers):
                digest, _ = self.write_archive([row()], headers=headers)
                with self.assertRaises(ValueError):
                    self.read(digest)

    def test_single_trailing_empty_header_is_allowed_only_with_empty_values(self):
        digest, _ = self.write_archive([row()])
        self.assertEqual(self.read(digest)[0][0][1][""], "")
        digest, _ = self.write_archive([row(**{"": "unexpected data"})])
        with self.assertRaisesRegex(ValueError, "unnamed trailing column"):
            self.read(digest)

    def test_missing_required_header_and_bad_row_width_are_rejected(self):
        digest, _ = self.write_archive([row()], headers=[h for h in self.headers if h != "Cancelled"])
        with self.assertRaisesRegex(ValueError, "missing required"):
            self.read(digest)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(self.headers)
        writer.writerow([row().get(h, "") for h in self.headers[:-1]])
        digest, _ = self.write_archive(payload=stream.getvalue().encode())
        with self.assertRaisesRegex(ValueError, "header width"):
            self.read(digest)

    def test_multiple_csv_members_and_excess_members_are_rejected(self):
        digest, _ = self.write_archive([row()], extra_members=[("other.csv", "anything")])
        with self.assertRaisesRegex(ValueError, "exactly one CSV"):
            self.read(digest)
        digest, _ = self.write_archive([row()], extra_members=[(f"extra{i}.txt", "x") for i in range(16)])
        with self.assertRaisesRegex(ValueError, "at most 16"):
            self.read(digest)

    def test_archive_and_advertised_decompressed_size_caps(self):
        digest, payload = self.write_archive([row()])
        with patch.object(READER, "MAX_ARCHIVE_BYTES", self.archive.stat().st_size - 1):
            with self.assertRaises(ValueError):
                self.read(digest)
        with patch.object(READER, "MAX_CSV_BYTES", len(payload) - 1):
            with self.assertRaisesRegex(ValueError, "decompressed byte limit"):
                self.read(digest)

    def test_digest_reader_enforces_actual_stream_bytes(self):
        raw = READER._DigestReader(io.BytesIO(b"abcdef"), 5)
        with io.BufferedReader(raw) as buffered:
            with self.assertRaisesRegex(ValueError, "Decompressed CSV exceeds"):
                buffered.read()

    def test_full_member_crc_is_checked_including_outside_cohort(self):
        headers = [*self.headers[:-1], "Note", ""]
        _, payload = self.write_archive([row(), row(Origin="DEN", Note="outside_marker")], headers=headers)
        content = bytearray(self.archive.read_bytes())
        with zipfile.ZipFile(self.archive) as bundle:
            offset = bundle.infolist()[0].header_offset
        filename_bytes, extra_bytes = struct.unpack_from("<HH", content, offset + 26)
        data_offset = offset + 30 + filename_bytes + extra_bytes
        changed_byte = data_offset + payload.index(b"outside_marker")
        content[changed_byte] = ord("X")
        self.archive.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()  # Allow archive identity, reject the corrupt member CRC.
        with self.assertRaises(zipfile.BadZipFile):
            self.read(digest)

    def test_source_record_limit_covers_unselected_rows(self):
        digest, _ = self.write_archive([row(), row(Origin="DEN")])
        with patch.object(READER, "MAX_SOURCE_ROWS", 1):
            with self.assertRaisesRegex(ValueError, "source record limit"):
                self.read(digest)

    def test_cohort_record_and_cell_limits_never_silently_truncate(self):
        digest, _ = self.write_archive([row(), row(Flight_Number_Reporting_Airline="2")])
        with patch.object(READER, "MAX_COHORT_ROWS", 1):
            with self.assertRaisesRegex(ValueError, "nothing was truncated"):
                self.read(digest)
        with patch.object(READER, "MAX_COHORT_CELLS", len(self.headers) * 2 - 1):
            with self.assertRaisesRegex(ValueError, "nothing was truncated"):
                self.read(digest)

    def test_selected_cohort_byte_cap_counts_utf8_values(self):
        headers = [*self.headers[:-1], "Note", ""]
        record = row(Note="é")
        value_bytes = sum(len(record.get(name, "").encode("utf-8")) for name in headers)
        digest, _ = self.write_archive([record], headers=headers)
        with patch.object(READER, "MAX_COHORT_BYTES", value_bytes - 1):
            with self.assertRaisesRegex(ValueError, "byte"):
                self.read(digest)
        with patch.object(READER, "MAX_COHORT_BYTES", value_bytes):
            self.assertEqual(len(self.read(digest)[0]), 1)

    def test_cohort_byte_cap_does_not_count_unselected_values(self):
        headers = [*self.headers[:-1], "Note", ""]
        selected = row(Note="é")
        value_bytes = sum(len(selected.get(name, "").encode("utf-8")) for name in headers)
        digest, _ = self.write_archive([selected, row(Origin="DEN", Note="outside" * 100)], headers=headers)
        with patch.object(READER, "MAX_COHORT_BYTES", value_bytes):
            self.assertEqual(len(self.read(digest)[0]), 1)

    def test_geographic_cohort_retains_all_statuses_without_metadata_in_raw(self):
        digest, _ = self.write_archive([
            row(), row(Cancelled="1", Flight_Number_Reporting_Airline="2"),
            row(Diverted="1", Flight_Number_Reporting_Airline="3"), row(Origin="DEN"),
        ])
        rows, _, manifest = self.read(digest)
        self.assertEqual([number for number, _ in rows], [2, 3, 4])
        self.assertEqual(manifest["source_rows_scanned"], 4)
        self.assertTrue(all(READER.SOURCE_LINE_FIELD not in raw for _, raw in rows))
        result = READER.validate_rows(rows, ZONES)
        self.assertEqual(result["source_status_counts"]["cohorts"]["normal"], 1)
        self.assertEqual(result["source_status_counts"]["cohorts"]["cancelled_only"], 1)
        self.assertEqual(result["source_status_counts"]["cohorts"]["diverted_only"], 1)

    def test_publish_artifact_has_lineage_and_complete_csv_hash(self):
        digest, _ = self.write_archive([row()])
        self.assertEqual(self.run_main(digest), 0)
        self.assertEqual({p.name for p in self.output.iterdir()}, {"cohort.csv", "validation.json", "validation.html"})
        html = (self.output / "validation.html").read_text()
        self.assertIn(hashlib.sha256((self.output / "validation.json").read_bytes()).hexdigest(), html)
        document = json.loads((self.output / "validation.json").read_text())
        self.assertEqual(document["cohort_artifact"]["sha256"], hashlib.sha256((self.output / "cohort.csv").read_bytes()).hexdigest())
        with (self.output / "cohort.csv").open(newline="") as handle:
            records = list(csv.DictReader(handle))
        self.assertEqual(records[0][READER.SOURCE_LINE_FIELD], "2")
        self.assertEqual(document["validation"]["input_rows"], 1)

    def test_existing_output_and_dangling_symlink_are_preserved(self):
        digest, _ = self.write_archive([row()])
        self.output.mkdir()
        marker = self.output / "previous"
        marker.write_bytes(b"keep")
        with self.assertRaises(SystemExit) as exc:
            self.run_main(digest)
        self.assertEqual(exc.exception.code, 2)
        self.assertEqual(marker.read_bytes(), b"keep")
        marker.unlink()
        self.output.rmdir()
        self.output.symlink_to(self.parent / "absent", target_is_directory=True)
        with self.assertRaises(SystemExit):
            self.run_main(digest)
        self.assertTrue(self.output.is_symlink())

    def test_publication_write_failure_leaves_no_final_and_retry_succeeds(self):
        digest, _ = self.write_archive([row()])
        original = READER._private_text_file
        def fail_json(path):
            if path.name == "validation.json":
                raise OSError("injected JSON publication failure")
            return original(path)
        with patch.object(READER, "_private_text_file", side_effect=fail_json):
            with self.assertRaises(SystemExit) as exc:
                self.run_main(digest)
        self.assertEqual(exc.exception.code, 2)
        self.assert_no_output()
        self.assertEqual(self.run_main(digest), 0)

    def test_html_failure_cannot_publish_json_and_csv_without_the_report(self):
        digest, _ = self.write_archive([row()])
        with patch.object(READER, "render_validation_html", side_effect=ValueError("injected rendering failure")):
            with self.assertRaises(SystemExit) as exc:
                self.run_main(digest)
        self.assertEqual(exc.exception.code, 2)
        self.assert_no_output()
        self.assertEqual(self.run_main(digest), 0)

    def test_destination_collision_during_publish_never_replaces_empty_directory(self):
        digest, _ = self.write_archive([row()])
        original = READER._publish_directory
        inodes = []
        def collide(staging, destination):
            destination.mkdir()
            inodes.append(destination.stat().st_ino)
            original(staging, destination)
        with patch.object(READER, "_publish_directory", side_effect=collide):
            with self.assertRaises(SystemExit):
                self.run_main(digest)
        self.assertEqual(self.output.stat().st_ino, inodes[0])
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_invalid_scan_creates_no_partial_output(self):
        digest, _ = self.write_archive([row(), row(Origin="DEN", FlightDate="2025-02-01")])
        with self.assertRaises(SystemExit) as exc:
            self.run_main(digest)
        self.assertEqual(exc.exception.code, 2)
        self.assert_no_output()


if __name__ == "__main__":
    unittest.main()
