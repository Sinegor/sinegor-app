"""Safety tests: no Docker, installation, or production calls."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    path = ROOT / (name + ".py")
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

transport = load("postgres_cli")
installer = load("install_production")

class TransportSafety(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(transport, "production transport is missing")

    def test_restore_and_alternate_connections_are_refused(self):
        for program, args in [
            ("pg_restore", ["--dbname", "service=sinegor_backup_api"]),
            ("psql", ["--dbname", "postgres://user:password@host/db"]),
            ("psql", ["--dbname", "service=sinegor_backup_api", "--host", "host"]),
            ("psql", ["-X", "-w", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                      "--dbname", "service=sinegor_backup_api", "-c", r"\! id"]),
        ]:
            with self.subTest(program=program):
                with self.assertRaises(transport.TransportError):
                    transport.parse_arguments(program, args)

    def test_capture_has_named_service_and_daemon_timeout(self):
        args = ["-w", "--format=custom", "--no-owner", "--no-acl", "--dbname",
                "service=sinegor_backup_api", "--file", "/private/api.dump"]
        parsed, target = transport.parse_arguments("pg_dump", args)
        command = transport.exec_command("pg_dump", parsed, "a" * 64)
        self.assertEqual(target, Path("/private/api.dump"))
        self.assertNotIn("--file", command)
        self.assertIn("--user", command)
        self.assertIn("postgres", command)
        self.assertIn("PGSERVICEFILE=/tmp/sinegor-backup/pg_service.conf", command)
        self.assertIn("PGPASSFILE=/tmp/sinegor-backup/pgpass", command)
        start = command.index("/usr/bin/timeout")
        self.assertEqual(command[start:start+4],
                         ["/usr/bin/timeout", "--signal=TERM", "--kill-after=5s", "100s"])
        self.assertNotIn("password", " ".join(command).lower())
        self.assertEqual(command[start + 4], "pg_dump", "Resolve tools through the pinned image PATH")

    def test_container_identity_includes_volume_source(self):
        item = {"Id": "a" * 64, "Image": "sha256:" + "b" * 64,
                "State": {"Running": True},
                "Config": {"Labels": {"com.docker.compose.project": "sinegor-lab-prod",
                                     "com.docker.compose.service": "postgres"}},
                "Mounts": [{"Type": "volume", "Name": "sinegor-lab-prod_postgres_data",
                            "Destination": "/var/lib/postgresql/data", "RW": True,
                            "Source": "/var/lib/docker/volumes/sinegor-lab-prod_postgres_data/_data"}]}
        self.assertEqual(transport.validate_postgres(item), "a" * 64)
        item["Mounts"][0]["Name"] = "unrelated"
        with self.assertRaises(transport.TransportError):
            transport.validate_postgres(item)

    def test_private_config_refuses_symlinks_and_open_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            source = root / "config.json"
            source.write_text("{}")
            source.chmod(0o600)
            self.assertEqual(transport.read_private_json(source, uid=os.getuid()), {})
            source.chmod(0o644)
            with self.assertRaises(transport.TransportError):
                transport.read_private_json(source, uid=os.getuid())
            source.chmod(0o600)
            alias = root / "alias"
            alias.symlink_to(source)
            with self.assertRaises(transport.TransportError):
                transport.read_private_json(alias, uid=os.getuid())

    def test_failed_capture_unlinks_partial_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            target = root / "api.dump"
            def failing(command, *, output=None):
                output.write(b"partial")
                raise transport.TransportError("failed")
            with self.assertRaises(transport.TransportError):
                transport.capture(["unused"], target, root=root, execute=failing, uid=os.getuid())
            self.assertFalse(target.exists())
            target.write_bytes(b"existing")
            with self.assertRaises(transport.TransportError):
                transport.capture(["unused"], target, root=root, execute=failing, uid=os.getuid())
            self.assertEqual(target.read_bytes(), b"existing")

class InstallerSafety(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(installer, "production installer is missing")

    def test_budget_preserves_growth_and_floor(self):
        self.assertEqual(installer.REQUIRED_FREE_BYTES, int(17.75 * 1024 ** 3))
        with self.assertRaises(installer.InstallError):
            installer.check_space(installer.REQUIRED_FREE_BYTES - 1)
        installer.check_space(installer.REQUIRED_FREE_BYTES)

    def test_mail_uses_alias_without_guessing_recipient(self):
        env = {"SMTP_HOST": "smtp.invalid", "SMTP_PORT": "465", "SMTP_USE_SSL": "true",
               "SMTP_USERNAME": "user", "SMTP_PASSWORD": "secret",
               "SMTP_FROM_EMAIL": "sender@example.invalid",
               "NOTIFICATION_ADMIN_EMAIL": "admin@example.invalid"}
        result = installer.mail_settings(env)
        self.assertEqual(result["from"], "sender@example.invalid")
        self.assertEqual(result["recipient"], "admin@example.invalid")
        self.assertTrue(result["use_ssl"])
        del env["NOTIFICATION_ADMIN_EMAIL"]
        with self.assertRaisesRegex(installer.InstallError, "recipient"):
            installer.mail_settings(env)

    def test_existing_or_symlink_target_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "new"
            installer.require_absent(path)
            path.write_bytes(b"owned elsewhere")
            with self.assertRaises(installer.InstallError):
                installer.require_absent(path)
            path.unlink()
            path.symlink_to(root / "missing")
            with self.assertRaises(installer.InstallError):
                installer.require_absent(path)

    def test_configuration_starts_inactive_with_canonical_paths(self):
        config = installer.configuration()
        self.assertFalse(config["activation_approved"])
        self.assertEqual(config["project"], "sinegor-lab-prod")
        self.assertEqual(config["repository"], "/var/lib/sinegor-backup/repository")
        self.assertEqual(config["restic_password_file"], "/etc/sinegor/backup/restic-password")
        self.assertEqual(config["postgres_container"], "sinegor-lab-prod-postgres-1")
        self.assertEqual(config["resume_timeout"], 180)

    def test_role_sql_has_select_only_privileges_and_no_app_role_mutation(self):
        sql = installer.role_sql("api", "strong_generated_token_12345")
        for fragment in ("NOSUPERUSER NOCREATEDB NOCREATEROLE",
                         "NOINHERIT NOREPLICATION NOBYPASSRLS",
                         "default_transaction_read_only", "GRANT SELECT ON ALL TABLES",
                         "GRANT SELECT ON ALL SEQUENCES",
                         "ALTER DEFAULT PRIVILEGES FOR ROLE sinegor_owner",
                         "lock_timeout", "statement_timeout"):
            self.assertIn(fragment, sql)
        self.assertNotIn("ALTER ROLE sinegor_api ", sql)
        self.assertNotIn("GRANT ALL", sql)
        with self.assertRaises(installer.InstallError):
            installer.role_sql("api", "unsafe'password")

    def test_systemd_ordering_timeouts_and_daily_schedule(self):
        root = ROOT.parents[1] / "infra/scheduler"
        service = (root / "sinegor-backup.service").read_text()
        for fragment in ("TimeoutStartSec=20min", "TimeoutStopSec=180s",
                         "ExecStopPost=/usr/bin/python3 /usr/local/lib/sinegor/backup/production.py recover",
                         "OnFailure=sinegor-backup-watchdog.service"):
            self.assertIn(fragment, service)
        timer = (root / "sinegor-backup.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 02:30:00 Europe/Moscow", timer)
        self.assertIn("Persistent=true", timer)
        recovery = (root / "sinegor-backup-recovery.service").read_text()
        for name in ("minute", "cleanup_agreements", "purge_security_events",
                     "purge_auth", "purge_analytics", "cleanup_business"):
            self.assertIn("sinegor-job-" + name + ".timer", recovery)
        self.assertIn("sinegor-backup.timer", recovery)
        self.assertIn("RemainAfterExit=true", recovery)


class AdditionalSafety(unittest.TestCase):
    def test_capture_process_timeout_reaps_local_child_and_hides_stderr(self):
        self.assertIsNotNone(transport)
        import sys
        from unittest.mock import patch
        processes = []
        original = transport.subprocess.Popen
        def tracking(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(transport.subprocess, "Popen", side_effect=tracking):
            with self.assertRaises(transport.TransportError) as error:
                transport.execute([sys.executable, "-c",
                    "import sys,time;sys.stderr.write('private_value');sys.stderr.flush();time.sleep(60)"],
                    timeout=0.05)
        self.assertNotIn("private_value", str(error.exception))
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())

    def test_preflight_detects_incompatible_timer_targets_before_any_write(self):
        self.assertIsNotNone(installer)
        from unittest.mock import patch
        with patch.object(installer, "check_target_conflicts", side_effect=installer.InstallError("conflict")) as check:
            with patch.object(installer, "write_new") as write:
                with patch.object(installer, "PRIVATE", Path("/path/that/does/not/exist")):
                    with self.assertRaisesRegex(installer.InstallError, "conflict"):
                        installer.prepare()
                write.assert_not_called()
            check.assert_called_once()

    def test_mail_header_and_starttls_values_are_safe(self):
        self.assertIsNotNone(installer)
        env = {"SMTP_HOST": "smtp.invalid", "SMTP_PORT": "587", "SMTP_USE_SSL": "false",
               "SMTP_USERNAME": "user", "SMTP_PASSWORD": "secret",
               "SMTP_FROM": "sender@example.invalid", "NOTIFICATION_ADMIN_EMAIL": "admin@example.invalid"}
        self.assertFalse(installer.mail_settings(env)["use_ssl"])
        env["NOTIFICATION_ADMIN_EMAIL"] = "admin@example.invalid\r\nBcc: other@example.invalid"
        with self.assertRaises(installer.InstallError):
            installer.mail_settings(env)

    def test_recovery_kit_contains_only_explicit_private_files(self):
        self.assertIsNotNone(installer)
        import tarfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            for name in ("restic-password", "pg_service.conf", "pgpass", "config.json", "mail.json"):
                target = root / name
                target.write_bytes(b"fixture secret")
                target.chmod(0o600)
            with patch.object(installer, "PRIVATE", root), patch.object(os, "getuid", return_value=0):
                # Testing owner checking separately allows ordinary-user tests.
                original = installer.file_bytes
                def read(path, **kwargs):
                    return original(path, private=kwargs.get("private", False), owners=(os.geteuid(),))
                with patch.object(installer, "file_bytes", side_effect=read):
                    installer.recovery_kit({"api.env": b"fixture", "cms.env": b"fixture",
                                            "compose.env": b"fixture", "security-cleanup.env": b"fixture"})
            self.assertEqual(stat_mode(root / "recovery.tar"), 0o600)
            with tarfile.open(root / "recovery.tar") as archive:
                self.assertEqual(set(archive.getnames()), {"restic-password", "pg_service.conf", "pgpass",
                    "config.json", "mail.json", "api.env", "cms.env", "compose.env", "security-cleanup.env", "recovery.json"})
            with patch.object(installer, "PRIVATE", root):
                with self.assertRaises(FileExistsError):
                    installer.recovery_kit({})

def stat_mode(path):
    import stat
    return stat.S_IMODE(path.stat().st_mode)

if __name__ == "__main__":
    unittest.main()
