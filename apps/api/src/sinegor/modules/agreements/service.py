"""Lock order first, then agreement; store immutable objects before publishing references."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from sinegor.db.types import AgreementStatus, OrderStatus
from sinegor.modules.agreements.models import Agreement, AgreementFileDeletion
from sinegor.modules.agreements.storage import AgreementStorage, AgreementStorageError, validate_pdf
from sinegor.modules.notifications.service import enqueue
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import locked_order, record_event, transition

logger = logging.getLogger(__name__)
STORAGE_LOCK = 0x53494E45414752


def get_agreement(db: Session, order_id: UUID) -> Agreement:
    agreement = db.scalar(select(Agreement).where(Agreement.order_id == order_id))
    if agreement is None:
        raise HTTPException(404, "Agreement not found")
    return agreement


def editable_order(db: Session, order_id: UUID) -> tuple[Order, Agreement | None]:
    order = locked_order(db, order_id)
    if order.status != OrderStatus.AWAITING_AGREEMENT:
        raise HTTPException(409, "Order is not awaiting an agreement")
    agreement = db.scalar(
        select(Agreement)
        .where(Agreement.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, agreement


def check_revision(agreement: Agreement | None, revision: int) -> None:
    if revision != (agreement.revision if agreement else 0):
        raise HTTPException(409, "Agreement version changed; reload the document")


def queue_deletion(db: Session, order_id: UUID, key: str | None) -> None:
    if key is not None:
        db.add(AgreementFileDeletion(order_id=order_id, file_key=key))


def is_referenced(db: Session, key: str) -> bool:
    return (
        db.scalar(
            select(Agreement.id)
            .where(
                or_(
                    Agreement.initial_pdf_key == key,
                    Agreement.returned_pdf_key == key,
                    Agreement.final_pdf_key == key,
                )
            )
            .limit(1)
        )
        is not None
    )


def cleanup_files(db: Session, storage: AgreementStorage, order_id: UUID | None = None) -> int:
    statement = select(AgreementFileDeletion).order_by(AgreementFileDeletion.id)
    if order_id is not None:
        statement = statement.where(AgreementFileDeletion.order_id == order_id)
    pending = db.scalars(statement.with_for_update(skip_locked=True)).all()
    removed = 0
    for item in pending:
        if is_referenced(db, item.file_key):
            continue  # Even an erroneous queue item must never delete an active/final PDF.
        try:
            storage.delete(item.file_key)
        except AgreementStorageError:
            logger.error("agreement_file_cleanup_failed")
            continue
        db.delete(item)
        record_event(db, db.get(Order, item.order_id), "agreement_file_deleted")
        removed += 1
    db.commit()
    return removed


def finish(db: Session, storage: AgreementStorage, order_id: UUID) -> None:
    db.commit()
    # References are already durable: a failed unlink must not undo approval or lose retry state.
    try:
        cleanup_files(db, storage, order_id)
    except Exception as exc:
        db.rollback()
        logger.error("agreement_file_cleanup_failed", extra={"exception_type": type(exc).__name__})


def upload(
    db: Session,
    storage: AgreementStorage,
    order_id: UUID,
    data: bytes,
    revision: int,
    actor_id: UUID,
    *,
    initial: bool,
    authorize: Callable[[], object] | None = None,
) -> Agreement:
    validate_pdf(data)
    if authorize is not None:
        authorize()
    order, agreement = editable_order(db, order_id)
    check_revision(agreement, revision)
    if initial:
        if agreement is not None and agreement.status not in {
            AgreementStatus.AWAITING_CUSTOMER,
            AgreementStatus.REJECTED,
        }:
            raise HTTPException(
                409, "A document under review cannot be replaced by the administrator"
            )
    elif (
        agreement is None
        or agreement.initial_pdf_key is None
        or agreement.status == AgreementStatus.APPROVED
    ):
        raise HTTPException(409, "An initial agreement is required")
    # Cleanup takes the exclusive counterpart, so it cannot remove an uncommitted upload.
    db.execute(select(func.pg_advisory_xact_lock_shared(STORAGE_LOCK)))
    key, digest = storage.put(data)
    if agreement is None:
        agreement = Agreement(order_id=order_id, revision=1)
        db.add(agreement)
    else:
        agreement.revision += 1
    if initial:
        queue_deletion(db, order_id, agreement.initial_pdf_key)
        queue_deletion(db, order_id, agreement.returned_pdf_key)
        agreement.initial_pdf_key, agreement.initial_sha256 = key, digest
        agreement.returned_pdf_key, agreement.returned_sha256 = None, None
        agreement.status = AgreementStatus.AWAITING_CUSTOMER
    else:
        queue_deletion(db, order_id, agreement.returned_pdf_key)
        agreement.returned_pdf_key, agreement.returned_sha256 = key, digest
        agreement.status = AgreementStatus.UNDER_REVIEW
    agreement.verified_at = agreement.verified_by_id = agreement.rejection_reason = None
    record_event(
        db,
        order,
        "agreement_initial_uploaded" if initial else "agreement_returned_uploaded",
        admin_id=actor_id if initial else None,
        customer_id=None if initial else actor_id,
    )
    kind = "agreement_initial" if initial else "agreement_returned"
    enqueue(
        db,
        kind,
        order_id=order.id,
        customer_id=order.customer_id,
        recipient=order.customer.email if initial else None,
        payload={"revision": agreement.revision},
        dedup_key=f"{kind}:{order.id}:{agreement.revision}",
    )
    finish(db, storage, order_id)
    return agreement


def review(
    db: Session,
    storage: AgreementStorage,
    order_id: UUID,
    revision: int,
    admin_id: UUID,
    *,
    reason: str | None = None,
) -> Agreement:
    order, agreement = editable_order(db, order_id)
    if agreement is None:
        raise HTTPException(404, "Agreement not found")
    check_revision(agreement, revision)
    if agreement.status != AgreementStatus.UNDER_REVIEW or agreement.returned_pdf_key is None:
        raise HTTPException(409, "Agreement is not awaiting review")
    if reason is None:
        _, digest = storage.read(agreement.returned_pdf_key, agreement.returned_sha256)
        agreement.final_pdf_key, agreement.final_sha256 = agreement.returned_pdf_key, digest
        queue_deletion(db, order_id, agreement.initial_pdf_key)
        agreement.initial_pdf_key = agreement.initial_sha256 = None
        agreement.status = AgreementStatus.APPROVED
        event_type = "agreement_approved"
    else:
        queue_deletion(db, order_id, agreement.returned_pdf_key)
        agreement.status = AgreementStatus.REJECTED
        agreement.rejection_reason = reason.strip()
        event_type = "agreement_rejected"
    agreement.returned_pdf_key = agreement.returned_sha256 = None
    agreement.verified_at = datetime.now(UTC)
    agreement.verified_by_id = admin_id
    agreement.revision += 1
    record_event(db, order, event_type, admin_id)
    if reason is None:
        transition(db, order, OrderStatus.AWAITING_MATERIALS, admin_id)
    kind = "agreement_approved" if reason is None else "agreement_rejected"
    enqueue(
        db,
        kind,
        order_id=order.id,
        customer_id=order.customer_id,
        recipient=order.customer.email,
        payload={"revision": agreement.revision},
        dedup_key=f"{kind}:{order.id}:{agreement.revision}",
    )
    finish(db, storage, order_id)
    return agreement


def cleanup_orphans(db: Session, storage: AgreementStorage, *, now: datetime | None = None) -> int:
    # No order locks or audit inserts here: uploads acquire order -> shared storage lock.
    db.execute(select(func.pg_advisory_xact_lock(STORAGE_LOCK)))
    references = set()
    for row in db.execute(
        select(Agreement.initial_pdf_key, Agreement.returned_pdf_key, Agreement.final_pdf_key)
    ):
        references.update(key for key in row if key is not None)
    references.update(db.scalars(select(AgreementFileDeletion.file_key)))
    from sinegor.modules.retention.models import RetentionFileDeletion

    references.update(db.scalars(select(RetentionFileDeletion.file_key)))
    keys = storage.orphan_keys(references, (now or datetime.now(UTC)) - timedelta(days=1))
    for key in keys:
        storage.delete(key)
    db.commit()
    return len(keys)
