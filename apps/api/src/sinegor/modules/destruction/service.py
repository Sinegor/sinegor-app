"""Transactional evidence first; PDF retries never perform physical destruction."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sinegor.modules.destruction.documents import render_documents, snapshot
from sinegor.modules.destruction.models import DestructionOperation
from sinegor.modules.retention.archive import RetentionArchive
from sinegor.modules.retention.calendar import anniversary


def prepare(db: Session, *, key: str, kind: str, metadata: dict) -> DestructionOperation:
    db.execute(
        insert(DestructionOperation)
        .values(
            id=uuid4(),
            idempotency_key=key,
            kind=kind,
            state="preparing",
            metadata_json=metadata,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    operation = db.scalar(
        select(DestructionOperation)
        .where(DestructionOperation.idempotency_key == key)
        .with_for_update()
    )
    if operation.kind != kind:
        raise ValueError("Idempotency key belongs to a different operation")
    return operation


def confirm(db: Session, operation: DestructionOperation, *, now: datetime | None = None) -> None:
    if operation.destroyed_at is not None:
        return
    now = now or datetime.now(UTC)
    operation.expires_at = anniversary(now, 3)
    operation.destroyed_at = now
    operation.state, operation.error_code = "documents_pending", None
    db.flush()


def mark_error(operation: DestructionOperation, code: str, *, uncertain: bool = False) -> None:
    if operation.destroyed_at is None:
        operation.state = "uncertain" if uncertain else "error"
        operation.error_code = code


def generate(
    db: Session, identifier: UUID, archive: RetentionArchive, *, now: datetime | None = None
) -> DestructionOperation:
    operation = db.scalar(
        select(DestructionOperation)
        .where(DestructionOperation.id == identifier)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if operation is None or operation.destroyed_at is None:
        raise ValueError("Destruction is not confirmed")
    if operation.expires_at <= (now or datetime.now(UTC)):
        raise ValueError("Document retention has expired")
    operation.updated_at = datetime.now(UTC)
    try:
        key = operation.bundle_key or archive.find_operation(operation.destroyed_at, operation.id)
        # Recover a complete filesystem publication after loss of the DB commit.
        if key is not None:
            frozen = json.loads(archive.read(key, "event.json"))
            if frozen["operation_id"] != str(operation.id):
                raise ValueError("Bundle belongs to a different event")
            export = "journal_export.pdf" if "/" in key else "extract.pdf"
            for name in ("act.pdf", export):
                archive.read(key, name)
        else:
            frozen = snapshot(
                operation_id=operation.id,
                kind=operation.kind,
                destroyed_at=operation.destroyed_at,
                metadata=operation.metadata_json,
            )
            files = render_documents(frozen)
            files["journal_export.pdf"] = files.pop("extract.pdf")
            files["event.json"] = json.dumps(frozen, ensure_ascii=False, sort_keys=True).encode()
            key = archive.store(operation.destroyed_at, files, operation_id=operation.id)
        operation.bundle_key, operation.state, operation.error_code = key, "ready", None
    except Exception:
        # Rendering libraries have their own exception classes. Preserve the
        # confirmed event and a safe retry state without exposing source values.
        operation.state = "documents_pending"
        operation.error_code = "documents_generation_failed"
    return operation


def generate_pending(db: Session, archive: RetentionArchive, *, limit: int = 100) -> dict:
    ids = db.scalars(
        select(DestructionOperation.id)
        .where(
            DestructionOperation.destroyed_at.is_not(None),
            DestructionOperation.state != "ready",
            DestructionOperation.expires_at > datetime.now(UTC),
        )
        .order_by(DestructionOperation.updated_at, DestructionOperation.id)
        .limit(limit)
    ).all()
    db.rollback()
    ready = failed = 0
    for identifier in ids:
        try:
            op = generate(db, identifier, archive)
            db.commit()
            ready += op.state == "ready"
            failed += op.state != "ready"
        except Exception:
            db.rollback()
            failed += 1
    return {"ready": ready, "failed": failed}


def cleanup_expired(db: Session, *, now: datetime | None = None, dry_run: bool = True) -> int:
    now = now or datetime.now(UTC)
    anniversary(now, 0)
    ids = db.scalars(
        select(DestructionOperation.id).where(DestructionOperation.expires_at <= now)
    ).all()
    if not dry_run and ids:
        db.execute(delete(DestructionOperation).where(DestructionOperation.id.in_(ids)))
        db.commit()
    return len(ids)
