"""Acceptance regressions: no receipt or rotation for an unverified backup."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / "backup.py"
SNAPSHOT = "a" * 64

FAKE = r"""
import json,os,shutil,sys
from pathlib import Path
action=sys.argv[1]
root=Path(os.environ["SYNTHETIC_PRIVATE"])
if Path(sys.argv[0]).name=="pg_dump":
    Path(sys.argv[sys.argv.index("--file")+1]).write_bytes(b"synthetic dump")
elif action=="backup":
    if os.environ.get("REQUIRE_CAPTURED") and not (root/"captured").exists():
        sys.exit(9)
    shutil.copytree(Path.cwd(),root/"saved")
    print(json.dumps({"message_type":"summary","snapshot_id":"a"*64}))
elif action=="snapshots":
    items=[{"id":"a"*64,"hostname":"sinegor","tags":["sinegor-managed-v1"]}]
    if os.environ.get("INVENTORY_CHANGED") and sys.argv[-1] != "a"*64:
        counter=root/"inventory-reads"
        reads=int(counter.read_text())+1 if counter.exists() else 1
        counter.write_text(str(reads))
        if reads > 1:
            items.append({"id":"b"*64,"hostname":"sinegor","tags":["sinegor-managed-v1"]})
    print(json.dumps([] if os.environ.get("MISSING_SNAPSHOT") else items))
elif action=="restore":
    shutil.copytree(root/"saved",Path(sys.argv[-1]),dirs_exist_ok=True)
elif action=="check":
    sys.exit(1 if os.environ.get("CORRUPT_REPOSITORY") else 0)
elif action=="forget":
    if "--dry-run" in sys.argv:
        print(json.dumps([] if os.environ.get("EMPTY_RETENTION") else
            [{"keep":[{"id":"a"*64}],"remove":[]}]))
    else:
        (root/"forget-called").touch()
"""


class AcceptanceTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location("acceptance_backup", TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def environment(self, root):
        binary = root / "bin"
        binary.mkdir()
        for name in ("restic", "pg_dump"):
            path = binary / name
            path.write_text(f"#!{sys.executable}\n" + FAKE)
            path.chmod(0o700)
        return {
            "PATH": str(binary) + os.pathsep + os.environ.get("PATH", ""),
            "RESTIC_REPOSITORY": str(root / "repository"),
            "RESTIC_PASSWORD_FILE": str(root / "password"),
            "SYNTHETIC_PRIVATE": str(root),
        }

    def arguments(self, root):
        for name in ("agreements", "media"):
            (root / name).mkdir()
        return SimpleNamespace(
            agreements=root / "agreements", uploads=root / "media",
            destruction_archive=None, api_service="source_api", cms_service="source_cms",
            receipt=root / "receipt.json",
        )

    def test_missing_snapshot_never_produces_success_receipt(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.arguments(root)
            with (
                patch.dict(os.environ, self.environment(root) | {"MISSING_SNAPSHOT": "yes"}),
                patch.object(tool, "database_info", side_effect=[
                    {"name": "source_api"}, {"name": "source_cms"}]),
                patch.object(tool, "agreement_files", return_value={}),
                patch.object(tool, "media_files", return_value={}),
            ):
                with self.assertRaises(tool.BackupError):
                    tool.backup(args)
            self.assertFalse(args.receipt.exists())

    def test_capture_callback_resumes_before_restic_and_verified_receipt(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.arguments(root)
            with (
                patch.dict(os.environ, self.environment(root) | {"REQUIRE_CAPTURED": "yes"}),
                patch.object(tool, "database_info", side_effect=[
                    {"name": "source_api"}, {"name": "source_cms"}]),
                patch.object(tool, "agreement_files", return_value={}),
                patch.object(tool, "media_files", return_value={}),
            ):
                try:
                    tool.backup(args, on_captured=lambda: (root / "captured").touch())
                except TypeError:
                    self.fail("backup must support resuming writers after capture")
            self.assertEqual(json.loads(args.receipt.read_text())["snapshot"], SNAPSHOT)
            self.assertEqual(set(p.name for p in (root / "saved").iterdir()),
                             {"agreements", "media", "api.dump", "cms.dump", "manifest.json"})

    def test_corrupt_repository_is_rejected_before_any_forget(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, self.environment(root) | {"CORRUPT_REPOSITORY": "yes"}):
                with self.assertRaises(tool.BackupError):
                    tool.rotate(SimpleNamespace(execute=True))
            self.assertFalse((root / "forget-called").exists())

    def test_hanging_tool_has_bounded_failure_without_upstream_output(self):
        tool = self.module()
        started = time.monotonic()
        error = None
        try:
            tool.run([sys.executable, "-c", "import time;time.sleep(1)"], timeout=0.02)
        except Exception as caught:
            error = caught
        self.assertIsInstance(error, tool.BackupError)
        self.assertLess(time.monotonic() - started, 0.5)


    def saved_backup(self, root):
        saved = root / "saved"
        saved.mkdir()
        files = {}
        for name in ("api.dump", "cms.dump"):
            content = ("synthetic " + name).encode()
            (saved / name).write_bytes(content)
            files[name] = hashlib.sha256(content).hexdigest()
        manifest = {"version": 1, "databases": ["source_api", "source_cms"], "files": files}
        (saved / "manifest.json").write_text(json.dumps(manifest))
        return saved, manifest

    def test_incomplete_manifest_is_never_accepted(self):
        tool = self.module()
        for change in ("missing_api", "missing_cms", "same_database", "missing_databases"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                saved, manifest = self.saved_backup(Path(directory))
                if change in ("missing_api", "missing_cms"):
                    name = "api.dump" if change == "missing_api" else "cms.dump"
                    manifest["files"].pop(name)
                    (saved / name).unlink()
                elif change == "same_database":
                    manifest["databases"] = ["source_api", "source_api"]
                else:
                    manifest.pop("databases")
                (saved / "manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(tool.BackupError):
                    tool.verify_manifest(saved)

    def test_unaccepted_or_malformed_receipt_is_rejected_before_restore(self):
        tool = self.module()
        receipts = [
            {"version": 1, "snapshot": SNAPSHOT, "verified": False},
            {"version": 1, "snapshot": SNAPSHOT},
            {"version": 1, "snapshot": SNAPSHOT, "verified": "true"},
            {"version": 1, "snapshot": 123, "verified": True},
            {"version": 1, "snapshot": "a" * 8, "verified": True},
            {"version": 2, "snapshot": SNAPSHOT, "verified": True}, [],
        ]
        for receipt in receipts:
            with self.subTest(receipt=receipt), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = SimpleNamespace(receipt=root / "receipt.json", target=root / "restored",
                                       api_service="restore_api", cms_service="restore_cms")
                args.receipt.write_text(json.dumps(receipt))
                def no_tool(*_args, **_kwargs):
                    self.fail("Invalid receipt reached an external tool")
                with patch.dict(os.environ, self.environment(root)), patch.object(tool, "run", no_tool):
                    with self.assertRaises(tool.BackupError):
                        tool.restore_test(args)
                self.assertFalse(args.target.exists())


    def test_foreign_snapshot_is_rejected_before_restore_or_database_access(self):
        tool = self.module()
        for host, tags in (("foreign", ["sinegor-managed-v1"]), ("sinegor", ["foreign"])):
            with self.subTest(host=host, tags=tags), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = SimpleNamespace(receipt=root / "receipt.json", target=root / "restored",
                                       api_service="restore_api", cms_service="restore_cms")
                args.receipt.write_text(json.dumps(
                    {"version": 1, "snapshot": SNAPSHOT, "verified": True}))
                def external(command, **_kwargs):
                    if command[1] != "snapshots":
                        self.fail("Foreign snapshot reached restore")
                    return json.dumps([{"id": SNAPSHOT, "hostname": host, "tags": tags}])
                with patch.dict(os.environ, self.environment(root)), patch.object(tool, "run", external):
                    with self.assertRaises(tool.BackupError):
                        tool.restore_test(args)
                self.assertFalse(args.target.exists())

    def test_timeout_prevents_delayed_child_and_grandchild_writes(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grandchild = (
                "import pathlib,signal,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(.7);"
                f"pathlib.Path({str(root / 'grandchild')!r}).touch()")
            child = (
                "import pathlib,signal,subprocess,sys,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]);time.sleep(.7);"
                f"pathlib.Path({str(root / 'child')!r}).touch()")
            parent = (
                "import subprocess,sys,time;"
                f"subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(2)")
            with self.assertRaises(tool.BackupError):
                tool.run([sys.executable, "-c", parent], timeout=.2)
            time.sleep(.9)
            self.assertEqual(list(root.iterdir()), [])


    def test_empty_retention_plan_never_forgets(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, self.environment(root) | {"EMPTY_RETENTION": "yes"}):
                with self.assertRaises(tool.BackupError):
                    tool.rotate(SimpleNamespace(execute=True))
            self.assertFalse((root / "forget-called").exists())

    def test_rotation_invalid_kept_manifest_never_forgets(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved, _ = self.saved_backup(root)
            (saved / "manifest.json").unlink()
            with patch.dict(os.environ, self.environment(root)):
                with self.assertRaises(tool.BackupError):
                    tool.rotate(SimpleNamespace(execute=True))
            self.assertFalse((root / "forget-called").exists())

    def test_rotation_inventory_change_never_forgets(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.saved_backup(root)
            with patch.dict(os.environ, self.environment(root) | {"INVENTORY_CHANGED": "yes"}):
                with self.assertRaises(tool.BackupError):
                    tool.rotate(SimpleNamespace(execute=True))
            self.assertFalse((root / "forget-called").exists())
