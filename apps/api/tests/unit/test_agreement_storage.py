import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from pypdf import PdfWriter

from sinegor.core.config import API_ROOT, Settings
from sinegor.core.logging import configure_logging
from sinegor.modules.agreements import storage as agreement_storage
from sinegor.modules.agreements.storage import AgreementStorage, AgreementStorageError, validate_pdf


def test_private_objects_are_immutable_and_keep_original_bytes(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    output = BytesIO()
    writer.write(output)
    data = output.getvalue()
    validate_pdf(data)
    storage = AgreementStorage(tmp_path / "private")
    first, digest = storage.put(data)
    second, _ = storage.put(data)
    assert first != second
    assert storage.read(first, digest) == (data, hashlib.sha256(data).hexdigest())
    assert stat.S_IMODE(storage.root.stat().st_mode) == 0o700
    assert stat.S_IMODE((storage.root / first).stat().st_mode) == 0o600
    storage.delete(first)
    storage.delete(first)
    assert (storage.root / second).exists()


@pytest.mark.parametrize(
    "key", ["../outside.pdf", "/tmp/outside.pdf", "nested/a.pdf", "", "a.pdf\n"]
)
def test_storage_rejects_path_injection(tmp_path, key):
    storage = AgreementStorage(tmp_path / "private")
    with pytest.raises(AgreementStorageError):
        storage.read(key, None)
    with pytest.raises(AgreementStorageError):
        storage.delete(key)


def test_storage_does_not_follow_symlinks(tmp_path):
    storage = AgreementStorage(tmp_path / "private")
    storage.root.mkdir(mode=0o700)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"private outside content")
    key = "a" * 32 + ".pdf"
    (storage.root / key).symlink_to(outside)
    with pytest.raises(AgreementStorageError):
        storage.read(key, None)
    with pytest.raises(AgreementStorageError):
        storage.delete(key)
    assert storage.orphan_keys(set(), before=datetime.now(UTC) + timedelta(days=2)) == []
    assert outside.read_bytes() == b"private outside content"


def test_storage_rejects_a_publicly_readable_directory(tmp_path):
    root = tmp_path / "public_permissions"
    root.mkdir(mode=0o755)
    with pytest.raises(AgreementStorageError):
        AgreementStorage(root).put(b"PDF")


def test_orphan_scan_tolerates_concurrent_file_removal(tmp_path, monkeypatch):
    storage = AgreementStorage(tmp_path / "private")
    key, _ = storage.put(b"orphan")
    original_lstat = Path.lstat

    def removed(path, *args, **kwargs):
        if path.name == key:
            path.unlink()
            raise FileNotFoundError
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", removed)
    assert storage.orphan_keys(set(), before=datetime.now(UTC)) == []


@pytest.mark.parametrize(
    "path",
    [
        "relative/path",
        "/",
        str(API_ROOT.parent / "web/public/pdf"),
        str(API_ROOT.parent / "cms/public/pdf"),
    ],
)
def test_configuration_rejects_nonprivate_storage(path):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost/db",
            agreement_storage_dir=path,
        )


@pytest.mark.parametrize("limit", [0, 50 * 1024 * 1024 + 1])
def test_configuration_bounds_pdf_size(limit):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost/db",
            agreement_max_bytes=limit,
        )


def test_parser_diagnostics_and_validation_do_not_expose_pdf_content(capsys):
    configure_logging("DEBUG")
    logging.getLogger("pypdf._reader").warning("private-pdf-fragment")
    with pytest.raises(HTTPException) as caught:
        validate_pdf(b"%PDF-1.7\nprivate-pdf-fragment\n%%EOF")
    assert "private-pdf-fragment" not in str(caught.value)
    output = capsys.readouterr()
    assert "private-pdf-fragment" not in output.out + output.err


def amplified_pdf():
    attributes = b" ".join(f"/K{i} {i}".encode() for i in range(2000))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 4000 /Kids [" + b"3 0 R " * 4000 + b"] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] " + attributes + b" >>",
    ]
    data = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 4\n0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def test_pdf_amplification_does_not_exhaust_api_process_memory():
    # Bound the old implementation too: a failing regression must not exhaust the test runner.
    script = """
import json
import resource
import sys
from fastapi import HTTPException
from sinegor.modules.agreements.storage import validate_pdf

data = sys.stdin.buffer.read()
with open('/proc/self/status') as source:
    virtual = int(next(line.split()[1] for line in source if line.startswith('VmSize:'))) * 1024
resource.setrlimit(resource.RLIMIT_AS, (virtual + 192 * 1024 * 1024, 1024 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_CPU, (7, 7))
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
try:
    validate_pdf(data)
    status = 200
except HTTPException as exc:
    status = exc.status_code
growth = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
print(json.dumps({'status': status, 'rss_growth_kib': growth}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=amplified_pdf(),
        capture_output=True,
        timeout=12,
        check=True,
    )
    outcome = json.loads(result.stdout)
    assert outcome["status"] == 422
    assert outcome["rss_growth_kib"] < 64 * 1024, outcome


def test_validation_timeout_kills_worker_and_releases_capacity(tmp_path, monkeypatch):
    worker, pid_file = tmp_path / "worker.py", tmp_path / "worker.pid"
    worker.write_text(
        "import os, pathlib, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    with monkeypatch.context() as patch:
        patch.setattr(agreement_storage, "PDF_WORKER", worker)
        patch.setattr(agreement_storage, "PDF_TIMEOUT_SECONDS", 1)
        with pytest.raises(HTTPException) as caught:
            validate_pdf(b"%PDF-private-document")
        assert caught.value.status_code == 422
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    output = BytesIO()
    writer.write(output)
    validate_pdf(output.getvalue())


def test_validation_limits_concurrent_worker_processes(tmp_path, monkeypatch):
    worker, release = tmp_path / "worker.py", tmp_path / "release"
    ready = tmp_path / "ready"
    ready.mkdir()
    worker.write_text(
        "import os, pathlib, sys, time\n"
        f"pathlib.Path({str(ready)!r}, str(os.getpid())).touch()\n"
        f"while not pathlib.Path({str(release)!r}).exists():\n"
        "    time.sleep(0.01)\n"
        "sys.stdin.buffer.read()\n"
    )
    monkeypatch.setattr(agreement_storage, "PDF_WORKER", worker)
    monkeypatch.setattr(agreement_storage, "PDF_TIMEOUT_SECONDS", 10)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = [executor.submit(validate_pdf, b"%PDF-document") for _ in range(2)]
        try:
            deadline = time.monotonic() + 5
            while len(list(ready.iterdir())) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(list(ready.iterdir())) == 2
            with pytest.raises(HTTPException) as caught:
                validate_pdf(b"%PDF-document")
            assert caught.value.status_code == 503
            assert len(list(ready.iterdir())) == 2
        finally:
            release.touch()
            for future in pending:
                future.result(timeout=5)
    validate_pdf(b"%PDF-document")
