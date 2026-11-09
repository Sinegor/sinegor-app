"""Private document-bundle lifecycle for the future destruction-document generator.

Only immutable files, digests and the actual destruction timestamp are stored here.
This is not an operation register, act generator, or reconstruction of past deletions.
"""

import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sinegor.modules.retention.calendar import anniversary

BUNDLE = re.compile(r"[0-9a-f]{32}")
DOCUMENT = re.compile(r"[a-z][a-z0-9_-]*\.(pdf|csv|json)")


@dataclass
class ArchiveCleanup:
    removed: int = 0
    failed: int = 0


class RetentionArchive:
    def __init__(self, root: Path):
        self.root = root

    def _directory(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Archive requires a private real directory")

    @contextmanager
    def _lock(self):
        self._directory()
        descriptor = os.open(self.root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    @staticmethod
    def _sync(path):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _read(path):
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("Archive document must be a regular file")
            return source.read()

    def _manifest(self, directory):
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise ValueError("Archive bundle must be a real directory")
        manifest = json.loads(self._read(directory / "manifest.json"))
        timestamp = datetime.fromisoformat(manifest["destroyed_at"])
        anniversary(timestamp, 3)  # Validate timezone and calendar range.
        files = manifest["files"]
        if manifest["version"] != 1 or not isinstance(files, dict) or not files:
            raise ValueError("Invalid archive manifest")
        for name, digest in files.items():
            if (
                name == "manifest.json"
                or not DOCUMENT.fullmatch(name)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError("Invalid archive document reference")
        actual = {p.name for p in directory.iterdir()}
        if actual - (set(files) | {"manifest.json"}):
            raise ValueError("Unmanaged archive document")
        return timestamp, files

    def store(self, destroyed_at: datetime, files: dict[str, bytes]) -> str:
        anniversary(destroyed_at, 3)
        if not files or any(
            name == "manifest.json" or not DOCUMENT.fullmatch(name) for name in files
        ):
            raise ValueError("Use safe archive document names")
        key = uuid4().hex
        with self._lock():
            temporary = self.root / (".staging-" + key)
            temporary.mkdir(mode=0o700)
            manifest = {
                "version": 1,
                "destroyed_at": destroyed_at.astimezone(UTC).isoformat(),
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            }
            data_files = {"manifest.json": json.dumps(manifest).encode()} | files
            for name, data in data_files.items():
                descriptor = os.open(temporary / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
            self._sync(temporary)
            temporary.rename(self.root / key)
            self._sync(self.root)
        return key

    def references(self) -> dict[str, str]:
        references = {}
        if not self.root.exists() and not self.root.is_symlink():
            return references
        with self._lock():
            for directory in sorted(self.root.iterdir()):
                if not BUNDLE.fullmatch(directory.name):
                    continue
                _, files = self._manifest(directory)
                for name, expected in files.items():
                    data = self._read(directory / name)
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise ValueError("Archive integrity check failed")
                    references[f"{directory.name}/{name}"] = expected
                references[f"{directory.name}/manifest.json"] = hashlib.sha256(
                    self._read(directory / "manifest.json")
                ).hexdigest()
        return references

    def cleanup(self, *, now: datetime | None = None, dry_run: bool = True) -> ArchiveCleanup:
        now = now or datetime.now(UTC)
        anniversary(now, 0)
        result = ArchiveCleanup()
        if not self.root.exists() and not self.root.is_symlink():
            return result
        # dry-run never creates directories/lock files or updates manifests.
        if dry_run:
            self._inspect(now, result, dry_run=True)
        else:
            with self._lock():
                self._inspect(now, result, dry_run=False)
        return result

    def _inspect(self, now, result, *, dry_run):
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Archive requires a private real directory")
        for directory in sorted(self.root.iterdir()):
            if not BUNDLE.fullmatch(directory.name.removeprefix(".staging-")):
                continue
            try:
                # Empty owned bundles contain no personal data; finish an interrupted rmdir.
                if stat.S_ISDIR(directory.lstat().st_mode) and not any(directory.iterdir()):
                    if not dry_run:
                        directory.rmdir()
                        self._sync(self.root)
                    result.removed += 1
                    continue
                destroyed_at, files = self._manifest(directory)
                if anniversary(destroyed_at, 3) > now:
                    continue
                if not dry_run:
                    for name in files:
                        path = directory / name
                        try:
                            if not stat.S_ISREG(path.lstat().st_mode):
                                raise ValueError("Archive document must be a regular file")
                            path.unlink()
                        except FileNotFoundError:
                            pass  # Retry after an interrupted unlink sequence.
                    self._sync(directory)
                    (directory / "manifest.json").unlink()
                    self._sync(directory)
                    directory.rmdir()
                    self._sync(self.root)
                result.removed += 1
            except (OSError, ValueError, KeyError, TypeError):
                result.failed += 1
