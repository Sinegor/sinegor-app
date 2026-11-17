#!/usr/bin/python3
"""Root-only, read-only PostgreSQL capture transport for the canonical container."""
import json
import os
import re
import signal
import stat
import subprocess
import sys
from pathlib import Path

PROJECT = "sinegor-lab-prod"
CONFIG = "/etc/sinegor/backup/config.json"
SERVICES = {"service=sinegor_backup_api", "service=sinegor_backup_cms"}
PGVOLUME = PROJECT + "_postgres_data"
PGSOURCE = "/var/lib/docker/volumes/" + PGVOLUME + "/_data"


class TransportError(Exception):
    """Safe diagnostic: command output and SQL values are never included."""


def private(info, *, uid=0, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != uid
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or (not directory and info.st_nlink != 1)):
        raise TransportError("Unsafe private backup path")


def read_private_json(path, *, uid=0):
    path = Path(path)
    try:
        private(path.parent.lstat(), uid=uid, directory=True)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as source:
            private(os.fstat(source.fileno()), uid=uid)
            return json.load(source)
    except (OSError, ValueError):
        raise TransportError("Private backup configuration is unavailable") from None


def parse_arguments(program, arguments):
    args = list(arguments)
    if program == "pg_dump":
        if (len(args) != 8 or args[:5] !=
                ["-w", "--format=custom", "--no-owner", "--no-acl", "--dbname"]
                or args[5] not in SERVICES or args[6] != "--file"
                or not Path(args[7]).is_absolute()):
            raise TransportError("Only the approved named backup services are permitted")
        return args[:6], Path(args[7])
    if program == "psql":
        if (len(args) != 10 or args[:7] !=
                ["-X", "-w", "-A", "-t", "-v", "ON_ERROR_STOP=1", "--dbname"]
                or args[7] not in SERVICES or args[8] != "-c"
                or not re.match(r"^\s*SELECT\b", args[9], flags=re.IGNORECASE)
                or "\\" in args[9]):
            raise TransportError("Only approved read-only backup queries are permitted")
        return args, None
    raise TransportError("Production restore and unsupported PostgreSQL tools are forbidden")


def validate_postgres(item):
    try:
        labels = item["Config"]["Labels"]
        matches = [mount for mount in item["Mounts"]
                   if mount.get("Destination") == "/var/lib/postgresql/data"]
        if (labels.get("com.docker.compose.project") != PROJECT
                or labels.get("com.docker.compose.service") != "postgres"
                or item["State"]["Running"] is not True
                or not re.fullmatch(r"[0-9a-f]{64}", item["Id"])
                or len(matches) != 1
                or any(matches[0].get(key) != value for key, value in
                       {"Type": "volume", "Name": PGVOLUME, "Source": PGSOURCE, "RW": True}.items())):
            raise TransportError("Production PostgreSQL identity or mount differs")
        return item["Id"]
    except (KeyError, TypeError):
        raise TransportError("Invalid production PostgreSQL identity") from None


def exec_command(program, arguments, container):
    return [
        "/usr/bin/docker", "exec", "--user", "postgres", "-i",
        "--env", "PGSERVICEFILE=/tmp/sinegor-backup/pg_service.conf",
        "--env", "PGPASSFILE=/tmp/sinegor-backup/pgpass",
        "--env", "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=95000 -c lock_timeout=3000",
        container, "/usr/bin/timeout", "--signal=TERM", "--kill-after=5s", "100s",
        program, *arguments,
    ]


def execute(command, *, output=None, timeout=112):
    """Kill only the owned local process group; the daemon-side reader is bounded."""
    process = None
    try:
        process = subprocess.Popen(command, stdout=output if output is not None else subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True,
                                   env={"PATH": "/usr/local/bin:/usr/bin:/bin"})
        result, _ = process.communicate(timeout=timeout)
        if process.returncode:
            raise TransportError("PostgreSQL capture command failed")
        return result
    except BaseException as error:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        if isinstance(error, (OSError, subprocess.TimeoutExpired)):
            raise TransportError("PostgreSQL capture unavailable or timed out") from None
        raise


def capture(command, target, *, root, execute=execute, uid=0):
    target, root = Path(target), Path(root)
    owned = False
    try:
        private(root.lstat(), uid=uid, directory=True)
        relative = target.relative_to(root)
        if not relative.parts or any(part in {".", ".."} for part in relative.parts):
            raise TransportError("Capture output is outside the private staging directory")
        parent = root
        for part in relative.parts[:-1]:
            parent = parent / part
            private(parent.lstat(), uid=uid, directory=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        owned = True
        with os.fdopen(fd, "wb") as output:
            execute(command, output=output)
            output.flush()
            os.fsync(output.fileno())
    except BaseException as error:
        if owned:
            target.unlink(missing_ok=True)
        if isinstance(error, (OSError, ValueError)):
            raise TransportError("Capture output is unavailable or already exists") from None
        raise


def main(argv=None):
    if os.geteuid() != 0:
        raise TransportError("Production PostgreSQL capture requires root")
    program = Path(sys.argv[0]).name
    arguments, target = parse_arguments(program, sys.argv[1:] if argv is None else argv)
    path = Path(os.environ.get("SINEGOR_BACKUP_CONFIG", CONFIG))
    if path != Path(CONFIG):
        raise TransportError("Only the installed private production configuration is permitted")
    config = read_private_json(path)
    if (config.get("version") != 1 or config.get("project") != PROJECT
            or config.get("private_dir") != "/etc/sinegor/backup"
            or config.get("state_dir") != "/var/lib/sinegor-backup"
            or config.get("postgres_container") != PROJECT + "-postgres-1"):
        raise TransportError("Unexpected production configuration identity")
    # The controller stages these two verified host files before every capture.
    for filename in ("pg_service.conf", "pgpass"):
        with os.fdopen(os.open(path.parent / filename, os.O_RDONLY | os.O_NOFOLLOW)) as source:
            private(os.fstat(source.fileno()))
    items = json.loads(execute(["/usr/bin/docker", "inspect", config["postgres_container"]]))
    if not isinstance(items, list) or len(items) != 1:
        raise TransportError("Expected one canonical PostgreSQL container")
    container = validate_postgres(items[0])
    expected_image = config.get("images", {}).get("postgres")
    if not expected_image or items[0].get("Image") != expected_image:
        raise TransportError("PostgreSQL image differs from the approved installation")
    command = exec_command(program, arguments, container)
    if target is not None:
        capture(command, target, root=Path(config["state_dir"]) / "tmp")
    else:
        sys.stdout.buffer.write(execute(command))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TransportError, OSError, ValueError, KeyError, TypeError):
        print("Production PostgreSQL capture refused or failed; no success recorded", file=sys.stderr)
        raise SystemExit(1)
