"""Filesystem and refusal tests for the manual backup CLI."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "backup.py"


class BackupTests(unittest.TestCase):
    def module(self):
        self.assertTrue(TOOL.is_file(), "Manual backup CLI has not been implemented")
        spec = importlib.util.spec_from_file_location("backup_cli", TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_backup_requires_stopped_writers_before_running_tools(self):
        self.assertTrue(TOOL.is_file(), "Manual backup CLI has not been implemented")
        result = subprocess.run(
            [sys.executable, str(TOOL), "backup"], capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--writers-stopped", result.stderr)

    def test_selected_files_exclude_orphans_and_keep_original_bytes(self):
        tool = self.module()
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "final.pdf").write_bytes(b"synthetic final PDF")
            (source / "orphan.pdf").write_bytes(b"must not be copied")
            destination = root / "copy"
            destination.mkdir()
            digest = hashlib.sha256(b"synthetic final PDF").hexdigest()
            files = tool.copy_files(source, destination, {"final.pdf": digest})
            self.assertEqual(files, {"final.pdf": digest})
            self.assertEqual((destination / "final.pdf").read_bytes(), b"synthetic final PDF")
            self.assertFalse((destination / "orphan.pdf").exists())

    def test_file_traversal_and_symlinks_are_rejected(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside").write_bytes(b"must not be read")
            source = root / "source"
            source.mkdir()
            (source / "link").symlink_to(root / "outside")
            (source / "nested").symlink_to(root, target_is_directory=True)
            for name in (
                "../outside",
                "/outside",
                "link",
                "nested/outside",
                "a/../outside",
            ):
                with self.subTest(name=name), self.assertRaises(tool.BackupError):
                    tool.safe_file(source, name)

    def test_missing_and_corrupt_referenced_files_abort_copy(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "copy"
            source.mkdir()
            destination.mkdir()
            (source / "corrupt.pdf").write_bytes(b"changed")
            for name in ("absent.pdf", "corrupt.pdf"):
                with self.subTest(name=name), self.assertRaises(tool.BackupError):
                    tool.copy_files(source, destination, {name: "0" * 64})

    def test_manifest_detects_modified_dump_before_database_restore(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "api.dump").write_bytes(b"tampered")
            (root / "manifest.json").write_text(
                json.dumps({"version": 1, "files": {"api.dump": "0" * 64}})
            )
            with self.assertRaises(tool.BackupError):
                tool.verify_manifest(root)

    def test_restored_file_not_listed_in_manifest_is_rejected(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unexpected").write_bytes(b"unexpected material")
            (root / "manifest.json").write_text(json.dumps({"version": 1, "files": {}}))
            with self.assertRaises(tool.BackupError):
                tool.verify_manifest(root)

    def test_external_media_and_encoded_traversal_are_rejected(self):
        tool = self.module()
        for url in (
            "/uploads/../secret",
            "/uploads/%2e%2e/secret",
            "https://other/secret",
        ):
            with self.subTest(url=url), self.assertRaises(tool.BackupError):
                tool.media_name(url)
        self.assertEqual(tool.media_name("/uploads/synthetic.pdf"), "synthetic.pdf")

    def test_failed_tool_names_stage_without_exposing_upstream_output(self):
        tool = self.module()
        with self.assertRaises(tool.BackupError) as error:
            tool.run(
                [
                    sys.executable,
                    "-c",
                    "import sys;sys.stderr.write('sensitive SQL');sys.exit(1)",
                ]
            )
        self.assertIn(Path(sys.executable).name, str(error.exception))
        self.assertNotIn("sensitive SQL", str(error.exception))

    def test_empty_reference_set_still_requires_a_real_source_directory(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(tool.BackupError):
                tool.copy_files(root / "missing", root, {})


if __name__ == "__main__":
    unittest.main()


class RetentionTests(unittest.TestCase):
    module = BackupTests.module

    def test_archive_files_are_selected_and_hash_verified(self):
        import hashlib
        from datetime import UTC, datetime

        from sinegor.modules.retention.archive import RetentionArchive

        tool = self.module()
        with tempfile.TemporaryDirectory() as d:
            archive = RetentionArchive(Path(d) / "archive")
            key = archive.store(datetime(2026, 1, 1, tzinfo=UTC), {"act.pdf": b"act"})
            self.assertEqual(
                tool.archive_files(archive.root)[f"{key}/act.pdf"],
                hashlib.sha256(b"act").hexdigest(),
            )
            (archive.root / key / "act.pdf").write_bytes(b"corrupt")
            with self.assertRaises(tool.BackupError):
                tool.archive_files(archive.root)

    def test_rotation_preview_does_not_prune_and_execution_keeps_7_daily_4_weekly(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        tool = self.module()
        with patch.object(tool, "restic_environment"), patch.object(tool, "run") as run:
            tool.rotate(SimpleNamespace(execute=False))
            command = run.call_args.args[0]
            self.assertIn("--dry-run", command)
            self.assertNotIn("--prune", command)
            self.assertIn("7", command)
            self.assertIn("4", command)
            self.assertIn("host,tags", command)
            tool.rotate(SimpleNamespace(execute=True))
            self.assertIn("--prune", run.call_args_list[-2].args[0])
            self.assertEqual(run.call_args_list[-1].args[0], ["restic", "check"])

    def test_scheduled_backup_always_resumes_after_backup_failure_and_never_rotates(
        self,
    ):
        from types import SimpleNamespace
        from unittest.mock import patch

        tool = self.module()
        args = SimpleNamespace(
            quiesce_command=Path("/synthetic/stop"),
            resume_command=Path("/synthetic/start"),
        )
        with (
            patch.object(tool, "run") as run,
            patch.object(tool, "backup", side_effect=tool.BackupError("synthetic")),
            patch.object(tool, "rotate") as rotate,
        ):
            with self.assertRaises(tool.BackupError):
                tool.scheduled(args)
            self.assertEqual(
                [c.args[0] for c in run.call_args_list],
                [["/synthetic/stop"], ["/synthetic/start"]],
            )
            rotate.assert_not_called()
