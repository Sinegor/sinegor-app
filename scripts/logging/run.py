"""Run an existing service with stdout/stderr in private, age-rotated host files."""

import argparse
import os
import stat
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/var/log/sinegor"))
    parser.add_argument("role", choices=("api", "web", "proxy", "strapi"))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command or not args.directory.is_absolute():
        parser.error("Use an absolute log directory and a service command")
    try:
        args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = args.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Private real directory required")
        descriptor = os.open(
            args.directory / f"{args.role}.log",
            os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Regular log required")
            os.fchmod(descriptor, 0o600)
            os.dup2(descriptor, 1)
            os.dup2(descriptor, 2)
        finally:
            os.close(descriptor)
        os.execvp(command[0], command)
    except (OSError, ValueError):
        print("Service log setup or service startup failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
