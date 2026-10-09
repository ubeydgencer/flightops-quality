import contextlib
import copy
import errno
import hashlib
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class BtsValidationHtmlCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "bts_validation_html_cli_tested", ROOT / "examples/bts_validation_html.py"
        )
        cls.renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.renderer)
        cls.evidence_bytes = (ROOT / "docs/evidence/bts-2025-01-route-cohort.json").read_bytes()
        cls.evidence = json.loads(cls.evidence_bytes)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.parent = Path(folder.name)
        self.input = self.parent / "input.json"
        self.output = self.parent / "validation.html"
        self.input.write_bytes(self.evidence_bytes)

    def args(self):
        return ["--input", str(self.input), "--output", str(self.output)]

    def run_cli(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = self.renderer.main(self.args())
        self.assertEqual(stderr.getvalue(), "")
        return result, stdout.getvalue()

    def assert_cli_failure(self, message=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exc:
                self.renderer.main(self.args())
        self.assertEqual(exc.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("bts_validation_html:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        if message:
            self.assertIn(message, stderr.getvalue())
        return stderr.getvalue()

    def assert_no_partial_output(self):
        self.assertFalse(os.path.lexists(self.output))
        self.assertEqual({path.name for path in self.parent.iterdir()}, {self.input.name})

    def test_cli_publishes_html_with_exact_input_digest_without_mutating_input(self):
        # The BOM and whitespace are part of the artifact identity, not parsed JSON.
        payload = b"\xef\xbb\xbf" + self.evidence_bytes + b"\n  "
        self.input.write_bytes(payload)
        result, stdout = self.run_cli()
        self.assertEqual(result, 0)
        self.assertEqual(stdout.strip(), str(self.output))
        markup = self.output.read_text(encoding="utf-8")
        self.assertTrue(markup.startswith("<!doctype html>"))
        self.assertIn("Rendered validation JSON SHA-256", markup)
        self.assertIn(hashlib.sha256(payload).hexdigest(), markup)
        self.assertEqual(self.input.read_bytes(), payload)
        self.assertEqual({path.name for path in self.parent.iterdir()}, {self.input.name, self.output.name})

    def test_exact_two_mib_limit_is_accepted(self):
        self.assertEqual(self.renderer.MAX_EVIDENCE_BYTES, 2 * 1_048_576)
        payload = self.evidence_bytes + b" " * (self.renderer.MAX_EVIDENCE_BYTES - len(self.evidence_bytes))
        self.input.write_bytes(payload)
        self.assertEqual(self.run_cli()[0], 0)
        self.assertIn(hashlib.sha256(payload).hexdigest(), self.output.read_text(encoding="utf-8"))
        self.assertEqual(self.input.read_bytes(), payload)

    def test_duplicate_json_keys_at_top_level_and_nested_are_rejected(self):
        for payload in (b'{"source": {}, "source": {}}',
                        b'{"source": {"archive_name": "first", "archive_name": "second"}}'):
            with self.subTest(payload=payload):
                self.input.write_bytes(payload)
                self.assert_cli_failure("Duplicate JSON mapping key")
                self.assert_no_partial_output()
                self.assertEqual(self.input.read_bytes(), payload)

    def test_deep_json_and_decoder_recursion_fail_cleanly(self):
        for depth in (40, 2000):
            with self.subTest(depth=depth):
                payload = (self.evidence_bytes.rstrip()[:-1] + b', "deep": '
                           + b"[" * depth + b"0" + b"]" * depth + b"}")
                self.input.write_bytes(payload)
                self.assert_cli_failure()
                self.assert_no_partial_output()
                self.assertEqual(self.input.read_bytes(), payload)

    def test_input_over_two_mib_is_rejected_before_publication(self):
        payload = self.evidence_bytes + b" " * (self.renderer.MAX_EVIDENCE_BYTES + 1 - len(self.evidence_bytes))
        self.input.write_bytes(payload)
        self.assert_cli_failure("input size limit")
        self.assert_no_partial_output()
        self.assertEqual(self.input.read_bytes(), payload)

    def test_huge_integer_percentage_exits_two_without_a_traceback(self):
        document = copy.deepcopy(self.evidence)
        document["validation"]["source_input_kpis"]["all_source_rows"]["percent"] = 1 << 2048
        payload = json.dumps(document).encode("utf-8")
        self.input.write_bytes(payload)
        self.assert_cli_failure("disagrees with its recorded population")
        self.assert_no_partial_output()
        self.assertEqual(self.input.read_bytes(), payload)

    def test_existing_file_is_preserved(self):
        previous = b"previous report"
        self.output.write_bytes(previous)
        inode = self.output.stat().st_ino
        self.assert_cli_failure("already exists")
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(self.output.stat().st_ino, inode)
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_existing_directory_and_its_contents_are_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_bytes(b"previous contents")
        inode = self.output.stat().st_ino
        self.assert_cli_failure("already exists")
        self.assertEqual(self.output.stat().st_ino, inode)
        self.assertEqual(sentinel.read_bytes(), b"previous contents")
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_existing_dangling_symlink_is_preserved(self):
        target = self.parent / "absent.html"
        self.output.symlink_to(target)
        inode = self.output.lstat().st_ino
        self.assert_cli_failure("already exists")
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(os.readlink(self.output), str(target))
        self.assertEqual(self.output.lstat().st_ino, inode)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_identical_input_output_path_preserves_evidence(self):
        self.output = self.input
        inode = self.input.stat().st_ino
        self.assert_cli_failure("already exists")
        self.assertEqual(self.input.read_bytes(), self.evidence_bytes)
        self.assertEqual(self.input.stat().st_ino, inode)
        self.assertEqual(list(self.parent.iterdir()), [self.input])

    def test_fdopen_failure_closes_descriptor_cleans_staging_and_allows_retry(self):
        original_mkstemp = self.renderer.tempfile.mkstemp
        descriptors = []

        def capture_descriptor(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            descriptors.append(fd)
            return fd, path

        with patch.object(self.renderer.tempfile, "mkstemp", side_effect=capture_descriptor):
            with patch.object(self.renderer.os, "fdopen", side_effect=OSError("injected fdopen failure")):
                self.assert_cli_failure("injected fdopen failure")
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError) as exc:
            os.fstat(descriptors[0])
        self.assertEqual(exc.exception.errno, errno.EBADF)
        self.assert_no_partial_output()
        self.assertEqual(self.run_cli()[0], 0)

    def test_link_failure_cleans_staging_and_allows_retry(self):
        with patch.object(self.renderer.os, "link", side_effect=OSError("injected link failure")):
            self.assert_cli_failure("injected link failure")
        self.assert_no_partial_output()
        self.assertEqual(self.input.read_bytes(), self.evidence_bytes)
        self.assertEqual(self.run_cli()[0], 0)

    def test_file_created_immediately_before_link_is_never_replaced(self):
        original_link = self.renderer.os.link
        previous = b"concurrently published report"
        inodes = []

        def collide(source, destination, **kwargs):
            with Path(destination).open("xb") as handle:
                handle.write(previous)
            inodes.append(Path(destination).stat().st_ino)
            return original_link(source, destination, **kwargs)

        with patch.object(self.renderer.os, "link", side_effect=collide):
            self.assert_cli_failure()
        self.assertEqual(len(inodes), 1)
        self.assertEqual(self.output.stat().st_ino, inodes[0])
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(self.input.read_bytes(), self.evidence_bytes)
        self.assertFalse(list(self.parent.glob("*.staging")))

    def test_dangling_symlink_created_immediately_before_link_is_preserved(self):
        original_link = self.renderer.os.link
        target = self.parent / "absent.html"
        inodes = []

        def collide(source, destination, **kwargs):
            Path(destination).symlink_to(target)
            inodes.append(Path(destination).lstat().st_ino)
            return original_link(source, destination, **kwargs)

        with patch.object(self.renderer.os, "link", side_effect=collide):
            self.assert_cli_failure()
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(self.output.lstat().st_ino, inodes[0])
        self.assertEqual(os.readlink(self.output), str(target))
        self.assertFalse(target.exists())
        self.assertFalse(list(self.parent.glob("*.staging")))

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits are not portable to Windows")
    def test_published_html_permissions_are_private_even_with_permissive_umask(self):
        previous_umask = os.umask(0)
        try:
            self.assertEqual(self.run_cli()[0], 0)
        finally:
            os.umask(previous_umask)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
