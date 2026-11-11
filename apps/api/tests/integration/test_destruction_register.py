"""Frozen documents survive source deletion, retries and untrusted HTTP callers."""

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
import test_auth as auth_helpers
import test_orders as order_helpers
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from sinegor.modules.destruction import service
from sinegor.modules.destruction.models import DestructionOperation
from sinegor.modules.retention.archive import RetentionArchive

pytestmark = pytest.mark.integration
auth = auth_helpers.auth
actors = auth_helpers.actors
admin = order_helpers.admin


def metadata():
    return {
        "subjects": [
            {
                "identity": "Иванов Иван Иванович",
                "categories": ["Номер телефона"],
                "source": "customers.display_name",
            }
        ],
        "entity": {"customer_id": "11111111-1111-1111-1111-111111111111"},
        "source": "customers",
        "basis": None,
        "method": "Очистка phone в PostgreSQL",
        "initiator": "admin:test",
        "executor": "FastAPI",
    }


def prepare(db):
    return service.prepare(
        db, key="synthetic-phone-once", kind="customer_fields", metadata=metadata()
    )


def test_unconfirmed_cannot_generate_then_frozen_pair_is_idempotent(db_session, tmp_path):
    archive = RetentionArchive(tmp_path / "archive")
    op = prepare(db_session)
    db_session.commit()
    with pytest.raises(ValueError):
        service.generate(db_session, op.id, archive)
    db_session.rollback()
    service.confirm(db_session, op)
    db_session.commit()
    assert prepare(db_session).id == op.id
    service.generate(db_session, op.id, archive)
    db_session.commit()
    assert op.state == "ready"
    before = archive.read(op.bundle_key, "journal_export.pdf")
    service.generate(db_session, op.id, archive)
    db_session.commit()
    assert archive.read(op.bundle_key, "journal_export.pdf") == before
    assert len(list(archive.root.rglob("manifest.json"))) == 1
    frozen = json.loads(archive.read(op.bundle_key, "event.json"))
    assert frozen["basis"] is None
    assert frozen["subjects"][0]["identity"] == "Иванов Иван Иванович"
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE destruction_operations SET metadata_json='{}' WHERE id=:id"), {"id": op.id}
        )
        db_session.flush()
    db_session.rollback()


def test_archive_survives_failed_db_commit_without_new_bundle(db_session, tmp_path, monkeypatch):
    archive = RetentionArchive(tmp_path / "archive")
    op = prepare(db_session)
    service.confirm(db_session, op)
    db_session.commit()
    identifier = op.id
    service.generate(db_session, identifier, archive)
    db_session.rollback()  # Simulate losing the DB write after atomic filesystem rename.

    def must_not_render(_):
        raise RuntimeError("Already published documents must be recovered")

    monkeypatch.setattr(service, "render_documents", must_not_render)
    service.generate(db_session, identifier, archive)
    db_session.commit()
    assert len(list(archive.root.rglob("manifest.json"))) == 1
    assert db_session.get(DestructionOperation, identifier).state == "ready"


@pytest.mark.parametrize("failure", [OSError, RuntimeError])
def test_failed_render_retries_only_documents(db_session, tmp_path, monkeypatch, failure):
    archive = RetentionArchive(tmp_path / "archive")
    op = prepare(db_session)
    service.confirm(db_session, op)
    db_session.commit()
    original = service.render_documents

    def broken(_):
        raise failure("synthetic")

    monkeypatch.setattr(service, "render_documents", broken)
    assert service.generate(db_session, op.id, archive).state == "documents_pending"
    db_session.commit()
    assert op.destroyed_at is not None and op.error_code == "documents_generation_failed"
    monkeypatch.setattr(service, "render_documents", original)
    assert service.generate(db_session, op.id, archive).state == "ready"
    db_session.commit()


def test_private_document_routes_and_csrf(admin, actors, tmp_path):
    admin.app.state.settings.destruction_archive_dir = tmp_path / "archive"
    op = prepare(admin.db)
    service.confirm(admin.db, op)
    admin.db.commit()
    path = f"/api/admin/destructions/{op.id}"
    assert admin.client.post(path + "/documents").status_code == 403
    result = auth_helpers.post(admin, path + "/documents")
    assert result.status_code == 200 and result.json()["state"] == "ready"
    listing = admin.client.get(
        "/api/admin/destructions", params={"q": "Иванов", "kind": "customer_fields"}
    )
    assert len(listing.json()) == 1
    for name in ["act", "extract"]:
        response = admin.client.get(path + "/documents/" + name)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Content-Type"] == "application/pdf"
        assert "inline" in response.headers["Content-Disposition"]
        assert "Иванов Иван Иванович" in "".join(
            p.extract_text() for p in PdfReader(BytesIO(response.content)).pages
        )
    bundle = RetentionArchive(tmp_path / "archive").root / op.bundle_key
    (bundle / "act.pdf").write_bytes(b"corrupt")
    assert admin.client.get(path + "/documents/act").status_code == 409
    auth_helpers.post(admin, "/api/auth/logout")
    assert admin.client.get(path).status_code == 401
    auth_helpers.login_customer(admin)
    assert admin.client.get(path).status_code == 403
    assert admin.client.get(path + "/documents/extract").status_code == 403


def test_three_year_cleanup_has_no_recursive_destruction(db_session, tmp_path):
    archive = RetentionArchive(tmp_path / "archive")
    op = prepare(db_session)
    service.confirm(db_session, op, now=datetime(2023, 11, 9, tzinfo=UTC))
    db_session.commit()
    # Generate as if still within retention.
    service.generate(db_session, op.id, archive, now=datetime(2023, 11, 10, tzinfo=UTC))
    db_session.commit()
    now = datetime(2026, 11, 9, tzinfo=UTC)
    assert service.cleanup_expired(db_session, now=now, dry_run=True) == 1
    assert db_session.get(DestructionOperation, op.id) is not None
    assert archive.cleanup(now=now - timedelta(microseconds=1)).removed == 0
    assert archive.cleanup(now=now, dry_run=False).removed == 1
    assert service.cleanup_expired(db_session, now=now, dry_run=False) == 1
    assert db_session.scalars(select(DestructionOperation)).all() == []


def test_failed_metadata_does_not_starve_later_operations(db_session, tmp_path):
    archive = RetentionArchive(tmp_path / "archive")
    first = service.prepare(db_session, key="bad-first", kind="customer", metadata={})
    first.updated_at = datetime.now(UTC) - timedelta(seconds=1)
    service.confirm(db_session, first)
    second = service.prepare(db_session, key="good-next", kind="customer", metadata=metadata())
    service.confirm(db_session, second)
    db_session.commit()
    assert service.generate_pending(db_session, archive, limit=1)["failed"] == 1
    assert service.generate_pending(db_session, archive, limit=1)["ready"] == 1


@pytest.mark.parametrize(
    "kind",
    [
        "disk_folder",
        "consultation_auto",
        "consultation_manual",
        "security_events",
        "customer_fields",
        "agreement",
        "order_history",
        "customer",
    ],
)
def test_all_eight_kinds_have_two_matching_a4_documents(db_session, tmp_path, kind):
    archive = RetentionArchive(tmp_path / "archive")
    op = service.prepare(db_session, key=kind, kind=kind, metadata=metadata())
    service.confirm(db_session, op)
    db_session.commit()
    service.generate(db_session, op.id, archive)
    db_session.commit()
    assert op.state == "ready"
    texts = []
    for name in ["act.pdf", "journal_export.pdf"]:
        reader = PdfReader(BytesIO(archive.read(op.bundle_key, name)))
        assert all(abs(float(page.mediabox.width) - 595.28) < 1 for page in reader.pages)
        assert all(abs(float(page.mediabox.height) - 841.89) < 1 for page in reader.pages)
        texts.append("\n".join(page.extract_text() for page in reader.pages))
    frozen = json.loads(archive.read(op.bundle_key, "event.json"))
    for text_value in texts:
        for required in [
            frozen["date_moscow"],
            "Иванов Иван Иванович",
            "Номер телефона",
            "SINEGOR LAB",
            str(op.id),
        ]:
            assert required in text_value


def test_concurrent_prepare_and_generation_publish_one_pair(
    database_settings, alembic_config, tmp_path
):
    from concurrent.futures import ThreadPoolExecutor

    from alembic import command
    from sqlalchemy.orm import Session

    from sinegor.db.session import create_db_engine

    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    archive = RetentionArchive(tmp_path / "archive")

    def worker(_):
        with Session(engine) as db:
            op = service.prepare(
                db, key="concurrent-only-once", kind="customer_fields", metadata=metadata()
            )
            service.confirm(db, op)
            db.commit()
            identifier = op.id
            service.generate(db, identifier, archive)
            db.commit()
            return identifier

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(worker, range(2)))
        assert ids[0] == ids[1]
        assert len(list(archive.root.rglob("manifest.json"))) == 1
        with Session(engine) as db:
            assert db.get(DestructionOperation, ids[0]).state == "ready"
    finally:
        engine.dispose()


def test_calendar_bundle_uses_confirmation_time_and_new_export_name(db_session, tmp_path):
    archive = RetentionArchive(tmp_path / "archive")
    op = prepare(db_session)
    service.confirm(db_session, op, now=datetime(2026, 12, 31, 22, 32, 15, tzinfo=UTC))
    db_session.commit()
    service.generate(db_session, op.id, archive)
    db_session.commit()
    assert op.state == "ready"
    assert op.bundle_key == "2027/2027-01-01_01-32-15"
    assert (archive.root / op.bundle_key / "journal_export.pdf").exists()
    assert not (archive.root / op.bundle_key / "extract.pdf").exists()
    frozen = json.loads(archive.read(op.bundle_key, "event.json"))
    assert frozen["operation_id"] == str(op.id)


def test_legacy_bundle_is_reused_without_render_or_file_changes(db_session, tmp_path, monkeypatch):
    archive = RetentionArchive(tmp_path / "archive")
    op = prepare(db_session)
    service.confirm(db_session, op)
    db_session.commit()
    frozen = service.snapshot(
        operation_id=op.id, kind=op.kind, destroyed_at=op.destroyed_at, metadata=op.metadata_json
    )
    files = service.render_documents(frozen)
    files["event.json"] = json.dumps(frozen).encode()
    key = archive.store(op.destroyed_at, files, key=op.id.hex)
    before = archive.references()

    def broken(_):
        raise RuntimeError("Legacy documents must remain unchanged")

    monkeypatch.setattr(service, "render_documents", broken)
    service.generate(db_session, op.id, archive)
    db_session.commit()
    assert op.state == "ready" and op.bundle_key == key
    assert archive.references() == before
    assert not any(path.name.isdigit() for path in archive.root.iterdir())


def test_legacy_document_http_routes_keep_original_extract(admin, actors, tmp_path):
    archive = RetentionArchive(tmp_path / "archive")
    admin.app.state.settings.destruction_archive_dir = archive.root
    op = prepare(admin.db)
    service.confirm(admin.db, op)
    admin.db.commit()
    frozen = service.snapshot(
        operation_id=op.id, kind=op.kind, destroyed_at=op.destroyed_at, metadata=op.metadata_json
    )
    files = service.render_documents(frozen)
    files["event.json"] = json.dumps(frozen).encode()
    op.bundle_key = archive.store(op.destroyed_at, files, key=op.id.hex)
    op.state = "ready"
    admin.db.commit()
    response = admin.client.get(f"/api/admin/destructions/{op.id}/documents/extract")
    assert response.status_code == 200
    same_document = response.content == files["extract.pdf"]
    assert same_document
