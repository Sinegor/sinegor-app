"""Synthetic safety tests for production restore acceptance; never invokes Docker."""
import copy
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / "restore_acceptance.py"
RUN = "a" * 12
ID = "b" * 64
IMAGE = "sha256:" + "c" * 64


class RestoreAcceptanceTests(unittest.TestCase):
    def module(self):
        self.assertTrue(TOOL.is_file(), "isolated restore acceptance helper is missing")
        spec = importlib.util.spec_from_file_location("restore_acceptance", TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def inspection(self, tool, *, network="none", mounts=None):
        return {
            "Id": ID, "Name": "/sinegor-backup-test-" + RUN,
            "Config": {"Labels": {tool.LABEL: RUN}, "Image": IMAGE},
            "HostConfig": {"NetworkMode": network, "PortBindings": {},
                           "Privileged": False, "Binds": None},
            "Mounts": mounts or [],
            "NetworkSettings": {"Ports": {}, "Networks": {}},
        }

    def test_requires_existing_private_work_root(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            self.assertEqual(tool.private_root(root), root.resolve())
            root.chmod(0o755)
            with self.assertRaises(tool.AcceptanceError):
                tool.private_root(root)

    def test_refuses_symlink_work_root(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "real").mkdir(mode=0o700)
            (root / "link").symlink_to(root / "real")
            with self.assertRaises(tool.AcceptanceError):
                tool.private_root(root / "link")

    def test_receipt_requires_full_verified_snapshot(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            receipt.write_text(json.dumps({"version": 1, "snapshot": "a" * 64, "verified": True}))
            self.assertEqual(tool.snapshot_from_receipt(receipt), "a" * 64)
            for changes in ({"snapshot": "latest"}, {"verified": False}, {"version": 2}):
                receipt.write_text(json.dumps({"version": 1, "snapshot": "a" * 64,
                                               "verified": True} | changes))
                with self.assertRaises(tool.AcceptanceError):
                    tool.snapshot_from_receipt(receipt)

    def test_only_local_exact_image_ids_are_allowed(self):
        tool = self.module()
        self.assertEqual(tool.image_id(IMAGE), IMAGE)
        for invalid in ("postgres:16", "postgres@sha256:" + "c" * 64, "latest", ""):
            with self.assertRaises(tool.AcceptanceError):
                tool.image_id(invalid)

    def test_only_restic_access_is_inherited(self):
        tool = self.module()
        parent = {"RESTIC_REPOSITORY": "/private/repository",
                  "RESTIC_PASSWORD_FILE": "/private/password",
                  "DATABASE_URL": "PRODUCTION", "SMTP_PASSWORD": "PRODUCTION",
                  "PGSERVICEFILE": "/production/service", "RESTIC_PASSWORD": "DO_NOT_COPY"}
        env = tool.isolated_environment(Path("/private/test"), parent)
        self.assertEqual(env["RESTIC_REPOSITORY"], "/private/repository")
        self.assertEqual(env["RESTIC_PASSWORD_FILE"], "/private/password")
        for key in ("DATABASE_URL", "SMTP_PASSWORD", "PGSERVICEFILE", "RESTIC_PASSWORD"):
            self.assertNotIn(key, env)
        self.assertEqual(env["SINEGOR_ENV_FILE"], "/dev/null")
        self.assertEqual(env["HOME"], "/private/test")

    def test_postgres_has_no_network_ports_or_host_data_mounts(self):
        tool = self.module()
        command = tool.postgres_command(RUN, IMAGE, Path("/private/postgres.env"))
        self.assertIn("--pull=never", command)
        self.assertIn("--network=none", command)
        self.assertIn("--log-driver=none", command)
        self.assertIn("type=tmpfs,destination=/var/lib/postgresql/data,tmpfs-size=536870912", command)
        self.assertFalse(any(item in command for item in ("-p", "-P", "--publish", "--privileged")))
        self.assertEqual(command[-1], IMAGE)

    def test_inspection_rejects_wrong_identity_network_and_any_unexpected_mount(self):
        tool = self.module()
        expected = {"id": ID, "name": "sinegor-backup-test-" + RUN,
                    "network": "none", "mounts": [], "image": IMAGE}
        good = self.inspection(tool)
        tool.validate_container(good, expected, RUN)
        variants = []
        for key, value in (("Id", "d" * 64), ("Name", "/production")):
            changed = copy.deepcopy(good)
            changed[key] = value
            variants.append(changed)
        for changed_key, changed_value in (
            ("NetworkMode", "bridge"), ("PortBindings", {"5432/tcp": [{}]}),
            ("Privileged", True), ("Binds", ["/production:/data"]),
        ):
            changed = copy.deepcopy(good)
            changed["HostConfig"][changed_key] = changed_value
            variants.append(changed)
        changed = copy.deepcopy(good)
        changed["Config"]["Labels"][tool.LABEL] = "foreign"
        variants.append(changed)
        changed = copy.deepcopy(good)
        changed["Mounts"] = [{"Type": "bind", "Source": "/production", "Destination": "/data", "RW": True}]
        variants.append(changed)
        for changed in variants:
            with self.assertRaises(tool.AcceptanceError):
                tool.validate_container(changed, expected, RUN)

    def test_namespaced_app_requires_exact_private_readonly_mounts(self):
        tool = self.module()
        mounts = [("bind", "/private/media", "/app/public/uploads", False)]
        expected = {"id": ID, "name": "sinegor-backup-test-" + RUN,
                    "network": "container:" + "e" * 64, "mounts": mounts, "image": IMAGE}
        inspected = self.inspection(tool, network=expected["network"], mounts=[
            {"Type": "bind", "Source": "/private/media", "Destination": "/app/public/uploads", "RW": False}
        ])
        tool.validate_container(inspected, expected, RUN)
        inspected["Mounts"][0]["RW"] = True
        with self.assertRaises(tool.AcceptanceError):
            tool.validate_container(inspected, expected, RUN)

    def test_run_directory_can_only_be_deleted_with_exact_private_marker(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            private = tool.make_private(root, RUN)
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700)
            (private / "confidential").write_text("synthetic")
            tool.remove_private(root, private, RUN)
            self.assertFalse(private.exists())
            foreign = root / "foreign"
            foreign.mkdir()
            with self.assertRaises(tool.AcceptanceError):
                tool.remove_private(root, foreign, RUN)
            self.assertTrue(foreign.exists())

    def test_changed_marker_and_symlink_are_never_deleted(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            private = tool.make_private(root, RUN)
            (private / tool.MARKER).write_text("foreign")
            with self.assertRaises(tool.AcceptanceError):
                tool.remove_private(root, private, RUN)
            self.assertTrue(private.is_dir())

    def test_nonroot_execution_fails_before_any_docker_call(self):
        tool = self.module()
        with patch.object(tool.os, "geteuid", return_value=1000):
            with self.assertRaises(tool.AcceptanceError):
                tool.require_root()

    def test_tool_failure_does_not_export_output(self):
        tool = self.module()
        with self.assertRaises(tool.AcceptanceError) as error:
            tool.call([sys.executable, "-c", "print('CONFIDENTIAL SQL TOKEN');raise SystemExit(1)"])
        self.assertNotIn("CONFIDENTIAL", str(error.exception))

    def test_report_contains_aggregate_results_only(self):
        tool = self.module()
        report = tool.new_report()
        self.assertEqual(set(report), {"version", "success", "stages", "counts", "cleanup"})
        tool.record_failure(report, ValueError("SECRET URL SQL VALUE"))
        encoded = json.dumps(report)
        self.assertNotIn("SECRET", encoded)
        self.assertEqual(report["error_type"], "ValueError")

    def test_cleanup_failure_retains_private_data(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            private = tool.make_private(root, RUN)
            fixture = tool.Fixture(RUN, private, {})
            fixture.containers = [{"id": ID, "name": "sinegor-backup-test-" + RUN,
                                   "network": "none", "mounts": [], "image": IMAGE}]
            foreign = self.inspection(tool)
            foreign["Config"]["Labels"][tool.LABEL] = "foreign"
            with patch.object(tool, "call", return_value=json.dumps([foreign]).encode()) as runner:
                self.assertFalse(tool.cleanup(fixture, root))
            self.assertTrue(private.exists())
            self.assertEqual(runner.call_count, 1)

    def test_cleanup_removes_only_checked_id_before_private_data(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            private = tool.make_private(root, RUN)
            fixture = tool.Fixture(RUN, private, {})
            fixture.containers = [{"id": ID, "name": "sinegor-backup-test-" + RUN,
                                   "network": "none", "mounts": [], "image": IMAGE}]
            observed = []
            def runner(command, **kwargs):
                observed.append(command)
                self.assertTrue(private.exists())
                return json.dumps([self.inspection(tool)]).encode() if command[1] == "inspect" else b""
            with patch.object(tool, "call", side_effect=runner):
                self.assertTrue(tool.cleanup(fixture, root))
            self.assertEqual(observed[1], ["docker", "rm", "-f", ID])
            self.assertFalse(private.exists())

    def test_attached_outside_network_is_rejected_even_when_host_mode_says_none(self):
        tool = self.module()
        expected = {"id": ID, "name": "sinegor-backup-test-" + RUN,
                    "network": "none", "mounts": [], "image": IMAGE}
        inspected = self.inspection(tool)
        inspected["NetworkSettings"]["Networks"] = {
            "bridge": {"IPAddress": "172.18.0.2", "Gateway": "172.18.0.1"}
        }
        with self.assertRaises(tool.AcceptanceError):
            tool.validate_container(inspected, expected, RUN)

    def test_container_still_present_after_rm_prevents_private_deletion(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            private = tool.make_private(root, RUN)
            fixture = tool.Fixture(RUN, private, {})
            fixture.containers = [{"id": ID, "name": "sinegor-backup-test-" + RUN,
                                   "network": "none", "mounts": [], "image": IMAGE}]
            def runner(command, **kwargs):
                if command[1] == "inspect":
                    return json.dumps([self.inspection(tool)]).encode()
                return (ID + "\n").encode() if command[1] == "ps" else b""
            with patch.object(tool, "call", side_effect=runner):
                self.assertFalse(tool.cleanup(fixture, root))
            self.assertTrue(private.is_dir())

    def test_orphaned_unregistered_run_container_prevents_private_deletion(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            private = tool.make_private(root, RUN)
            fixture = tool.Fixture(RUN, private, {})
            with patch.object(tool, "call", return_value=(ID + "\n").encode()):
                self.assertFalse(tool.cleanup(fixture, root))
            self.assertTrue(private.is_dir())

    def test_synthetic_app_environment_has_no_production_endpoints(self):
        tool = self.module()
        api, cms = tool.application_environment("SYNTHETIC", "api_a_restore_test", "cms_a_restore_test")
        self.assertEqual(api["SINEGOR_ENV_FILE"], "/dev/null")
        self.assertEqual(cms["ENV_PATH"], "/dev/null")
        self.assertIn("@127.0.0.1:5432/api_a_restore_test", api["DATABASE_URL"])
        self.assertEqual(cms["DATABASE_NAME"], "cms_a_restore_test")
        for key in ("SMTP_USERNAME", "SMTP_PASSWORD", "TELEGRAM_BOT_TOKEN", "YANDEX_DISK_TOKEN"):
            self.assertEqual(api[key], "")

    def test_cli_invalid_image_has_safe_json_failure_without_traceback(self):
        self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outcome = __import__("subprocess").run(
                [sys.executable, str(TOOL), "--receipt", str(root / "receipt"),
                 "--restic", str(root / "restic"), "--work-root", str(root),
                 "--postgres-image", "invalid", "--api-image", IMAGE, "--cms-image", IMAGE,
                 "--report", str(root / "result")], capture_output=True, text=True,
            )
            self.assertEqual(outcome.returncode, 1)
            self.assertNotIn("Traceback", outcome.stderr)
            self.assertFalse(json.loads(outcome.stdout)["success"])

    def test_installed_restore_environment_uses_only_explicit_project_sources(self):
        tool = self.module()
        builder = getattr(tool, "restore_environment", None)
        self.assertIsNotNone(builder, "installed helper must configure explicit project source imports")
        env = builder(Path("/private/run"), {"PATH": "/usr/bin"}, "sinegor-backup-test-" + RUN,
                      Path("/canonical/project"))
        self.assertEqual(env["PYTHONPATH"], "/canonical/project/apps/api/src")
        self.assertEqual(env["PGSERVICEFILE"], "/private/run/pg_service.conf")
        self.assertEqual(env["SINEGOR_BACKUP_TEST_CONTAINER"], "sinegor-backup-test-" + RUN)

    def test_timeout_kills_descendant_after_its_parent_has_already_exited(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "delayed"
            child = "import pathlib,sys,time;time.sleep(0.3);pathlib.Path(sys.argv[1]).write_text('synthetic')"
            parent = "import subprocess,sys;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])"
            with self.assertRaises(tool.AcceptanceError):
                tool.call([sys.executable, "-c", parent, child, str(marker)], timeout=0.05)
            __import__("time").sleep(0.4)
            self.assertFalse(marker.exists(), "orphan process wrote after timeout and could race cleanup")


if __name__ == "__main__":
    unittest.main()
