"""Private immutable PDF objects. Client filenames and paths are never used."""

import hashlib
import hmac
import os
import re
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import BoundedSemaphore
from uuid import uuid4

from fastapi import HTTPException

MAX_STORED_BYTES = 50 * 1024 * 1024
KEY_PATTERN = re.compile(r"[0-9a-f]{32}\.pdf")
PDF_WORKER = Path(__file__).with_name("_pdf_worker.py")
PDF_TIMEOUT_SECONDS = 5
PDF_VALIDATORS = BoundedSemaphore(2)
INVALID_PDF = "A valid unencrypted PDF with at least one page is required"


class AgreementStorageError(Exception):
    pass


def validate_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        raise HTTPException(422, INVALID_PDF)
    if not PDF_VALIDATORS.acquire(blocking=False):
        raise HTTPException(503, "Agreement PDF validation is busy; retry later")
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(PDF_WORKER)],
            input=data,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PDF_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(422, INVALID_PDF) from exc
    except OSError as exc:
        raise HTTPException(503, "Agreement PDF validation is unavailable") from exc
    finally:
        PDF_VALIDATORS.release()
    if result.returncode == 2:
        raise HTTPException(503, "Agreement PDF validation is unavailable")
    if result.returncode != 0:
        raise HTTPException(422, INVALID_PDF)


class AgreementStorage:
    def __init__(self, root: Path):
        self.root = root

    def _directory(self) -> None:
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self.root.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise AgreementStorageError("Agreement directory must have mode 0700")
        except OSError as exc:
            raise AgreementStorageError("Agreement storage is unavailable") from exc

    def _path(self, key: str) -> Path:
        if not KEY_PATTERN.fullmatch(key):
            raise AgreementStorageError("Invalid storage key")
        return self.root / key

    def put(self, data: bytes) -> tuple[str, str]:
        self._directory()
        key = f"{uuid4().hex}.pdf"
        path = self._path(key)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            # A partial object has no database reference and is reclaimed by the cleanup job.
            raise AgreementStorageError("Could not store agreement PDF") from exc
        return key, hashlib.sha256(data).hexdigest()

    def read(self, key: str, expected_digest: str | None) -> tuple[bytes, str]:
        self._directory()
        try:
            descriptor = os.open(self._path(key), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise AgreementStorageError("Agreement object is not a regular file")
                data = source.read(MAX_STORED_BYTES + 1)
            digest = hashlib.sha256(data).hexdigest()
            if len(data) > MAX_STORED_BYTES or (
                expected_digest is not None and not hmac.compare_digest(digest, expected_digest)
            ):
                raise AgreementStorageError("Agreement integrity check failed")
            return data, digest
        except OSError as exc:
            raise AgreementStorageError("Agreement PDF is unavailable") from exc

    def delete(self, key: str) -> None:
        self._directory()
        path = self._path(key)
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise AgreementStorageError("Agreement object is not a regular file")
            path.unlink()
        except FileNotFoundError:
            pass  # A retry after unlink succeeded but the database commit failed.
        except OSError as exc:
            raise AgreementStorageError("Could not remove obsolete agreement PDF") from exc

    def orphan_keys(self, referenced: set[str], before: datetime) -> list[str]:
        self._directory()
        try:
            keys = []
            for path in self.root.iterdir():
                if not KEY_PATTERN.fullmatch(path.name) or path.name in referenced:
                    continue
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue  # Another cleanup worker already removed this object.
                if stat.S_ISREG(info.st_mode) and info.st_mtime < before.timestamp():
                    keys.append(path.name)
            return keys
        except OSError as exc:
            raise AgreementStorageError("Could not inspect agreement storage") from exc
