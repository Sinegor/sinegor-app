"""Test-only transport for real PostgreSQL CLI without sharing private host mounts."""

import os
import re
import subprocess
import sys
from pathlib import Path


def main():
    container = os.environ["SINEGOR_BACKUP_TEST_CONTAINER"]
    if not re.fullmatch(r"sinegor-backup-test-[0-9a-f]{12}", container):
        raise RuntimeError("Invalid fixture container identity")
    program = Path(sys.argv[0]).name
    arguments = sys.argv[1:]
    prefix = [
        "docker",
        "exec",
        "-i",
        "--env",
        "PGSERVICEFILE=/tmp/pg_service.conf",
        "--env",
        "PGPASSFILE=/tmp/pgpass",
        container,
        program,
    ]
    if program == "pg_dump":
        index = arguments.index("--file")
        target = Path(arguments[index + 1])
        del arguments[index : index + 2]
        with target.open("xb") as output:
            return subprocess.run([*prefix, *arguments], stdout=output).returncode
    if program == "pg_restore":
        source = Path(arguments.pop())
        with source.open("rb") as data:
            return subprocess.run([*prefix, *arguments], stdin=data).returncode
    if program != "psql":
        raise RuntimeError("Unsupported fixture PostgreSQL tool")
    return subprocess.run([*prefix, *arguments]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
