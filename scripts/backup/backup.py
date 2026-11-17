"""Manual pg_dump + Restic backups; restore only into empty *_restore_test databases."""

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


class BackupError(Exception):
    """Safe operator diagnostic, without tool output or database values."""


def run(command, *, cwd=None, timeout=900):
    try:
        with subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process:
            try:
                output, _ = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Tools may be local wrappers; kill their entire owned group before cleanup.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                raise BackupError(
                    f"{Path(command[0]).name} timed out; no success was recorded"
                ) from None
            if process.returncode:
                raise BackupError(
                    f"{Path(command[0]).name} failed; no successful result was recorded"
                )
            return output
    except OSError:
        raise BackupError("Required backup tool is unavailable") from None


def query(service, sql):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", service):
        raise BackupError("Use a named libpq service")
    output = run(
        [
            "psql",
            "-X",
            "-w",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "--dbname",
            f"service={service}",
            "-c",
            sql,
        ]
    )
    return json.loads(output)


def database_info(service):
    return query(
        service,
        """
        SELECT json_build_object('name', current_database(), 'objects', (
            WITH user_namespaces AS (
                SELECT oid, nspname FROM pg_namespace
                WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'
            )
            SELECT (SELECT count(*) FROM pg_class
                    WHERE relnamespace IN (SELECT oid FROM user_namespaces))
                 + (SELECT count(*) FROM pg_proc
                    WHERE pronamespace IN (SELECT oid FROM user_namespaces))
                 + (SELECT count(*) FROM pg_type
                    WHERE typnamespace IN (SELECT oid FROM user_namespaces))
                 + (SELECT count(*) FROM user_namespaces WHERE nspname <> 'public')
        ))
    """,
    )


def agreement_files(service):
    rows = query(
        service,
        """
        SELECT coalesce(json_agg(json_build_array(k, h)), '[]')
        FROM agreements CROSS JOIN LATERAL (VALUES
            (initial_pdf_key, initial_sha256), (returned_pdf_key, returned_sha256),
            (final_pdf_key, final_sha256)) refs(k,h) WHERE k IS NOT NULL
    """,
    )
    files = {}
    for key, digest in rows:
        if not re.fullmatch(r"[0-9a-f]{32}\.pdf", key) or not isinstance(digest, str):
            raise BackupError("Invalid agreement file reference")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError("Invalid agreement digest")
        if key in files and files[key] != digest:
            raise BackupError("Conflicting agreement digests")
        files[key] = digest
    return files


def media_name(url):
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise BackupError("Only local Strapi uploads are supported")
    if not path.startswith("/uploads/"):
        raise BackupError("Media reference is outside uploads")
    name = path[len("/uploads/") :]
    if not name or any(part in {"", ".", ".."} for part in name.split("/")):
        raise BackupError("Unsafe media reference")
    return name


def media_files(service):
    rows = query(
        service,
        """
        SELECT coalesce(json_agg(json_build_object(
            'url', url, 'formats', formats, 'provider', provider)), '[]') FROM files
    """,
    )
    files = {}
    for row in rows:
        if row["provider"] != "local":
            raise BackupError("CMS upload provider requires a separate backup procedure")
        for item in [row, *(row.get("formats") or {}).values()]:
            files[media_name(item["url"])] = None
    return files


def safe_file(root, name):
    parts = name.split("/")
    if (
        not name
        or PurePosixPath(name).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise BackupError("Unsafe backup file reference")
    path = Path(root)
    if path.is_symlink() or not path.is_dir():
        raise BackupError("Backup source must be a real directory")
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise BackupError("Symlinks are excluded from the backup set")
    if not path.is_file():
        raise BackupError("Referenced backup file is missing")
    return path


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def copy_files(source, destination, references):
    if source.is_symlink() or not source.is_dir():
        raise BackupError("Backup source must be a real directory")
    files = {}
    for name, expected in references.items():
        original = safe_file(source, name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(original, target)
        digest = sha256(target)
        if expected is not None and digest != expected:
            raise BackupError("Referenced file failed SHA-256 verification")
        files[name] = digest
    return files


def verify_manifest(root):
    try:
        manifest = json.loads(safe_file(root, "manifest.json").read_text())
    except (ValueError, OSError):
        raise BackupError("Invalid backup manifest") from None
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise BackupError("Unsupported backup manifest")
    databases = manifest.get("databases")
    if (
        not isinstance(databases, list) or len(databases) != 2
        or not all(isinstance(name, str) and name for name in databases)
        or databases[0] == databases[1]
        or not isinstance(manifest.get("files"), dict)
        or not {"api.dump", "cms.dump"}.issubset(manifest["files"])
    ):
        raise BackupError("Backup manifest requires both separate databases and dumps")
    expected = set(manifest["files"]) | {"manifest.json"}
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BackupError("Symlink found in restored backup")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise BackupError("Restored backup file set does not match manifest")
    for name, digest in manifest["files"].items():
        if sha256(safe_file(root, name)) != digest:
            raise BackupError("Restored backup failed SHA-256 verification")
    return manifest


def restic_environment():
    if not os.environ.get("RESTIC_REPOSITORY") or not os.environ.get("RESTIC_PASSWORD_FILE"):
        raise BackupError("Set RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE")


def archive_files(root):
    # This lifecycle layer has only standard-library dependencies; no dotenv or DB access.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api/src"))
    from sinegor.modules.retention.archive import RetentionArchive

    try:
        return RetentionArchive(root).references()
    except (OSError, ValueError, KeyError, TypeError):
        raise BackupError("Destruction archive validation failed") from None


def rotate(args):
    restic_environment()
    policy = [
        "restic", "forget", "--tag", "sinegor-managed-v1", "--host", "sinegor",
        "--group-by", "host,tags", "--keep-daily", "7", "--keep-weekly", "4",
    ]
    if not args.execute:
        run([*policy, "--dry-run"])
        return
    run(["restic", "check"])
    inventory = managed_snapshot_ids()
    try:
        plan = json.loads(run([*policy, "--json", "--dry-run"]))
    except (ValueError, TypeError):
        raise BackupError("Invalid retention preview") from None
    if not isinstance(plan, list):
        raise BackupError("Invalid retention preview")
    keep, remove = set(), set()
    for group in plan:
        if not isinstance(group, dict):
            raise BackupError("Invalid retention group")
        retained, removed = group.get("keep"), group.get("remove") or []
        if not isinstance(retained, list) or not retained or not isinstance(removed, list):
            raise BackupError("Retention requires verified retained snapshots")
        for entries, destination in ((retained, keep), (removed, remove)):
            for item in entries:
                if (
                    not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["id"])
                    or item["id"] in keep or item["id"] in remove
                ):
                    raise BackupError("Invalid retention snapshot identity")
                destination.add(item["id"])
    if not keep or keep | remove != inventory:
        raise BackupError("Retention preview does not cover the managed snapshot inventory")
    for snapshot in sorted(keep):
        verify_snapshot(snapshot)
    if managed_snapshot_ids() != inventory:
        raise BackupError("Snapshot inventory changed during retention verification")
    # Delete exactly the planned immutable IDs; never recompute the policy after verification.
    if remove:
        run(["restic", "forget", *sorted(remove), "--prune", "--max-repack-size", "256M"])
    run(["restic", "check"])


def scheduled(args):
    if not args.quiesce_command.is_absolute() or not args.resume_command.is_absolute():
        raise BackupError("Writer control commands must be absolute executable paths")
    # Resume even when quiesce fails after stopping only some writers.
    try:
        run([str(args.quiesce_command)])
        backup(args)
    finally:
        run([str(args.resume_command)])
    args.execute = True
    rotate(args)


def backup(args, *, on_captured=None):
    restic_environment()
    if args.receipt.exists() or not args.receipt.parent.is_dir():
        raise BackupError("Receipt requires a new file in an existing private directory")
    databases = [database_info(service)["name"] for service in (args.api_service, args.cms_service)]
    if databases[0] == databases[1]:
        raise BackupError("API and CMS must use separate databases")
    with tempfile.TemporaryDirectory(prefix="sinegor-backup-") as temporary:
        stage = Path(temporary)
        files = {}
        archive = getattr(args, "destruction_archive", None)
        sources = [
            ("agreements", args.agreements, agreement_files(args.api_service)),
            ("media", args.uploads, media_files(args.cms_service)),
        ]
        if archive is not None:
            references = archive_files(archive)
            if references:
                sources.append(("destruction", archive, references))
        for kind, source, references in sources:
            destination = stage / kind
            destination.mkdir(mode=0o700)
            selected = copy_files(source, destination, references)
            files.update({f"{kind}/{key}": digest for key, digest in selected.items()})
        for kind, service in (("api", args.api_service), ("cms", args.cms_service)):
            target = stage / f"{kind}.dump"
            run(
                [
                    "pg_dump",
                    "-w",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    f"service={service}",
                    "--file",
                    str(target),
                ],
                timeout=getattr(args, "capture_timeout", 120),
            )
            files[target.name] = sha256(target)
        manifest = {"version": 1, "databases": databases, "files": files}
        (stage / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if on_captured is not None:
            on_captured()
        output = run(
            [
                "restic",
                "backup",
                "--json",
                "--tag",
                "sinegor-managed-v1",
                "--host",
                "sinegor",
                ".",
            ],
            cwd=stage,
        )
        summaries = [json.loads(line) for line in output.splitlines()]
        snapshot = next(
            (
                line.get("snapshot_id")
                for line in summaries
                if line.get("message_type") == "summary"
            ),
            None,
        )
        if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot):
            raise BackupError("Restic did not confirm a complete snapshot")
        verify_snapshot(snapshot, expected_manifest=manifest)
        write_receipt(args.receipt, snapshot)



def managed_snapshot_ids(snapshot=None):
    """Validate the managed namespace and return exact immutable snapshot identities."""
    command = ["restic", "snapshots", "--json"]
    command += [snapshot] if snapshot is not None else [
        "--host", "sinegor", "--tag", "sinegor-managed-v1",
    ]
    try:
        items = json.loads(run(command))
    except (ValueError, TypeError):
        raise BackupError("Invalid snapshot inventory") from None
    if not isinstance(items, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", item["id"])
        or item.get("hostname") != "sinegor"
        or not isinstance(item.get("tags"), list)
        or "sinegor-managed-v1" not in item["tags"]
        for item in items
    ):
        raise BackupError("Snapshot identity or backup namespace verification failed")
    ids = {item["id"] for item in items}
    if len(ids) != len(items):
        raise BackupError("Duplicate snapshot identity")
    if snapshot is not None and ids != {snapshot}:
        raise BackupError("Snapshot identity or backup namespace verification failed")
    return ids


def verify_snapshot(snapshot, *, expected_manifest=None):
    """Read back this exact complete snapshot before accepting its receipt."""
    managed_snapshot_ids(snapshot)
    with tempfile.TemporaryDirectory(prefix="sinegor-verify-") as temporary:
        target = Path(temporary)
        run(["restic", "restore", snapshot, "--target", str(target)])
        manifest = verify_manifest(target)
        if expected_manifest is not None and manifest != expected_manifest:
            raise BackupError("Snapshot manifest differs from the captured manifest")


def write_receipt(path, snapshot):
    """Publish a complete, fsynced private receipt without replacing an existing one."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump({"version": 1, "snapshot": snapshot, "verified": True}, output)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore_test(args):
    restic_environment()
    try:
        receipt = json.loads(args.receipt.read_text())
    except (ValueError, OSError):
        raise BackupError("Invalid backup receipt") from None
    if (
        not isinstance(receipt, dict) or receipt.get("version") != 1
        or receipt.get("verified") is not True
        or not isinstance(receipt.get("snapshot"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", receipt["snapshot"])
    ):
        raise BackupError("Invalid backup receipt")
    snapshot = receipt["snapshot"]
    managed_snapshot_ids(snapshot)
    # mkdir without exist_ok also rejects existing empty directories and symlinks.
    args.target.mkdir(mode=0o700)
    # backup '.' stores selected files at the snapshot root, not under the staging path.
    run(["restic", "restore", snapshot, "--target", str(args.target)])
    manifest = verify_manifest(args.target)
    sources = manifest["databases"]
    targets = [database_info(service) for service in (args.api_service, args.cms_service)]
    names = [target["name"] for target in targets]
    if names[0] == names[1] or any(
        name in sources or not name.endswith("_restore_test") for name in names
    ):
        raise BackupError("Restore requires two separate non-source *_restore_test databases")
    if any(target["objects"] for target in targets):
        raise BackupError("Restore target databases must be empty")
    for kind, service in (("api", args.api_service), ("cms", args.cms_service)):
        run(
            [
                "pg_restore",
                "-w",
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-acl",
                "--dbname",
                f"service={service}",
                str(args.target / f"{kind}.dump"),
            ]
        )
    for name, digest in agreement_files(args.api_service).items():
        if sha256(safe_file(args.target / "agreements", name)) != digest:
            raise BackupError("Restored agreement does not match the database")
    archive_files(args.target / "destruction")
    for name in media_files(args.cms_service):
        safe_file(args.target / "media", name)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    create = subparsers.add_parser("backup")
    create.add_argument(
        "--writers-stopped",
        action="store_true",
        required=True,
        help="API/CMS writers and cleanup jobs have been stopped by the operator",
    )
    create.add_argument("--agreements", type=Path, required=True)
    create.add_argument("--uploads", type=Path, required=True)
    create.add_argument(
        "--destruction-archive",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "apps/api/storage/destruction",
    )
    routine = subparsers.add_parser("scheduled")
    routine.add_argument("--quiesce-command", type=Path, required=True)
    routine.add_argument("--resume-command", type=Path, required=True)
    routine.add_argument("--agreements", type=Path, required=True)
    routine.add_argument("--uploads", type=Path, required=True)
    routine.add_argument("--destruction-archive", type=Path, required=True)
    rotation = subparsers.add_parser("rotate")
    rotation.add_argument("--execute", action="store_true")
    restore = subparsers.add_parser("restore-test")
    restore.add_argument("--target", type=Path, required=True)
    for child in (create, restore, routine):
        child.add_argument("--api-service", required=True)
        child.add_argument("--cms-service", required=True)
        child.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "backup":
            backup(args)
        elif args.action == "scheduled":
            scheduled(args)
        elif args.action == "rotate":
            rotate(args)
        else:
            restore_test(args)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        print("Backup configuration or file validation failed", file=sys.stderr)
        return 1
    print(
        {
            "backup": "Backup completed",
            "scheduled": "Scheduled backup and rotation completed",
            "rotate": "Backup retention processed",
            "restore-test": "Test restore verified",
        }[args.action]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
