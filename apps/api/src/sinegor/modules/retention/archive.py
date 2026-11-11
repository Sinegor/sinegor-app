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
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sinegor.modules.retention.calendar import anniversary

BUNDLE = re.compile(r"[0-9a-f]{32}")
YEAR = re.compile(r"[0-9]{4}")
CALENDAR_BUNDLE = re.compile(
    r"(?P<year>[0-9]{4})/(?P=year)-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}"
    r"(?:_(?:0[2-9]|[1-9][0-9]+))?"
)
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

    @staticmethod
    def _valid_key(key):
        if BUNDLE.fullmatch(key):
            return True
        if not CALENDAR_BUNDLE.fullmatch(key):
            return False
        try:
            datetime.strptime(key.split("/")[1][:19], "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            return False
        return True

    @staticmethod
    def _private_directory(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Archive requires a private real directory")

    def _bundles(self):
        directories, invalid_years = [], 0
        for path in sorted(self.root.iterdir()):
            if BUNDLE.fullmatch(path.name.removeprefix(".staging-")):
                directories.append(path)
            elif YEAR.fullmatch(path.name):
                try:
                    self._private_directory(path)
                    directories.extend(
                        child
                        for child in sorted(path.iterdir())
                        if self._valid_key(f"{path.name}/{child.name}")
                    )
                except (OSError, ValueError):
                    invalid_years += 1
        return directories, invalid_years

    def _find_operation(self, destroyed_at, operation_id):
        local = destroyed_at.astimezone(ZoneInfo("Europe/Moscow"))
        base = local.strftime("%Y/%Y-%m-%d_%H-%M-%S")
        legacy = self.root / operation_id.hex
        candidates = [legacy] if legacy.exists() or legacy.is_symlink() else []
        year = self.root / base.split("/")[0]
        if year.exists() or year.is_symlink():
            self._private_directory(year)
            candidates.extend(
                child
                for child in sorted(year.iterdir())
                if (
                    child.name == base.split("/")[1]
                    or child.name.startswith(base.split("/")[1] + "_")
                )
                and self._valid_key(f"{year.name}/{child.name}")
            )
        for directory in candidates:
            stamp, files = self._manifest(directory)
            data = self._read(directory / "event.json")
            if hashlib.sha256(data).hexdigest() != files["event.json"]:
                raise ValueError("Archive integrity check failed")
            if json.loads(data)["operation_id"] == str(operation_id):
                if stamp != destroyed_at:
                    raise ValueError("Immutable confirmation timestamp differs")
                return directory.relative_to(self.root).as_posix()
        return None

    def find_operation(self, destroyed_at: datetime, operation_id: UUID) -> str | None:
        anniversary(destroyed_at, 3)
        with self._lock():
            return self._find_operation(destroyed_at, operation_id)

    def read(self, key: str, name: str) -> bytes:
        if not self._valid_key(key) or not DOCUMENT.fullmatch(name):
            raise ValueError("Invalid archive reference")
        with self._lock():
            directory = self.root / key
            if "/" in key:
                self._private_directory(directory.parent)
            _, files = self._manifest(directory)
            if name not in files:
                raise ValueError("Document is not in the bundle")
            data = self._read(directory / name)
            if hashlib.sha256(data).hexdigest() != files[name]:
                raise ValueError("Archive integrity check failed")
            return data

    def store(
        self,
        destroyed_at: datetime,
        files: dict[str, bytes],
        *,
        key: str | None = None,
        operation_id: UUID | None = None,
    ) -> str:
        anniversary(destroyed_at, 3)
        if not files or any(
            name == "manifest.json" or not DOCUMENT.fullmatch(name) for name in files
        ):
            raise ValueError("Use safe archive document names")
        if key is not None and (not self._valid_key(key) or operation_id is not None):
            raise ValueError("Invalid archive reference")
        if operation_id is not None:
            if json.loads(files["event.json"])["operation_id"] != str(operation_id):
                raise ValueError("Bundle belongs to a different event")
        with self._lock():
            if operation_id is not None:
                key = self._find_operation(destroyed_at, operation_id)
                if key is None:
                    base = destroyed_at.astimezone(ZoneInfo("Europe/Moscow")).strftime(
                        "%Y/%Y-%m-%d_%H-%M-%S"
                    )
                    key, suffix = base, 1
                    while (self.root / key).exists() or (self.root / key).is_symlink():
                        suffix += 1
                        key = f"{base}_{suffix:02d}"
            key = key or uuid4().hex
            target = self.root / key
            if "/" in key:
                target.parent.mkdir(mode=0o700, exist_ok=True)
                self._private_directory(target.parent)
                self._sync(self.root)
            if target.exists() or target.is_symlink():
                stamp, expected = self._manifest(target)
                if stamp != destroyed_at or set(expected) != set(files):
                    raise ValueError("Immutable bundle differs")
                for name, data in files.items():
                    current = self._read(target / name)
                    if current != data or hashlib.sha256(current).hexdigest() != expected[name]:
                        raise ValueError("Immutable document differs")
                return key
            temporary = self.root / (".staging-" + (uuid4().hex if "/" in key else key))
            # A previous crash may leave an incomplete staging directory. Preserve it;
            # use a fresh staging name and atomically publish only a complete bundle.
            if temporary.exists():
                temporary = self.root / (".staging-" + uuid4().hex)
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
            temporary.rename(target)
            self._sync(target.parent)
            if target.parent != self.root:
                self._sync(self.root)
        return key

    def references(self) -> dict[str, str]:
        references = {}
        if not self.root.exists() and not self.root.is_symlink():
            return references
        with self._lock():
            directories, invalid_years = self._bundles()
            if invalid_years:
                raise ValueError("Invalid archive year directory")
            for directory in directories:
                if directory.name.startswith(".staging-"):
                    continue
                _, files = self._manifest(directory)
                relative = directory.relative_to(self.root).as_posix()
                for name, expected in files.items():
                    data = self._read(directory / name)
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise ValueError("Archive integrity check failed")
                    references[f"{relative}/{name}"] = expected
                references[f"{relative}/manifest.json"] = hashlib.sha256(
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
        directories, invalid_years = self._bundles()
        result.failed += invalid_years
        for directory in directories:
            try:
                # Empty owned bundles contain no personal data; finish an interrupted rmdir.
                if stat.S_ISDIR(directory.lstat().st_mode) and not any(directory.iterdir()):
                    if not dry_run:
                        directory.rmdir()
                        self._sync(directory.parent)
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
                    self._sync(directory.parent)
                result.removed += 1
            except (OSError, ValueError, KeyError, TypeError):
                result.failed += 1
