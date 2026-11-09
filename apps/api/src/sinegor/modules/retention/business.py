"""Explicit expired business-graph removal with durable, private file retries.

No Disk API calls, no security journal privileges, no destruction register.
Each customer's transaction is isolated; PDF removal follows committed intents.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from sinegor.db.types import AgreementStatus, DeletionStatus, OrderStatus
from sinegor.modules.agreements.models import Agreement, AgreementFileDeletion
from sinegor.modules.agreements.service import STORAGE_LOCK, is_referenced
from sinegor.modules.agreements.storage import KEY_PATTERN, AgreementStorage, AgreementStorageError
from sinegor.modules.audit.models import CustomerEvent, OrderEvent
from sinegor.modules.auth.models import AuthToken
from sinegor.modules.auth.models import Session as AuthSession
from sinegor.modules.customers.models import Customer
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications.models import Notification
from sinegor.modules.orders.models import MaterialHandover, Order, PaymentRecord
from sinegor.modules.retention.calendar import anniversary
from sinegor.modules.retention.models import DeletionRequest, RetentionFileDeletion

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    orders: int = 0
    customers: int = 0
    pending_files: int = 0
    failed: int = 0
    candidates: list[dict] = field(default_factory=list)


def _eligible(db: Session, order: Order, now: datetime, *, unsigned: bool) -> bool:
    agreement = db.scalar(select(Agreement).where(Agreement.order_id == order.id))
    signed = agreement is not None and (
        agreement.status == AgreementStatus.APPROVED or agreement.final_pdf_key is not None
    )
    if signed:
        # Owner's explicit clarification: a signed cancelled order starts at cancellation.
        start = order.closed_at if order.status == OrderStatus.CANCELLED else order.fulfilled_at
        if (
            order.status
            not in {OrderStatus.RESULT_READY, OrderStatus.COMPLETED, OrderStatus.CANCELLED}
            or start is None
            or anniversary(start, 5) > now
        ):
            return False
    elif not unsigned or order.status != OrderStatus.CANCELLED:
        return False
    folder = db.scalar(select(DiskFolder).where(DiskFolder.order_id == order.id))
    request = db.scalar(select(DeletionRequest).where(DeletionRequest.order_id == order.id))
    # Losing these links would prevent the administrator completing a Disk operation.
    if folder is not None and folder.deleted_at is None:
        return False
    return request is None or request.status == DeletionStatus.PERFORMED


def _remove_order(db: Session, order: Order) -> None:
    agreement = db.scalar(select(Agreement).where(Agreement.order_id == order.id))
    keys = set(
        db.scalars(
            select(AgreementFileDeletion.file_key).where(AgreementFileDeletion.order_id == order.id)
        )
    )
    if agreement is not None:
        keys.update(
            k
            for k in (
                agreement.initial_pdf_key,
                agreement.returned_pdf_key,
                agreement.final_pdf_key,
            )
            if k
        )
    # Unexpected cross-order references are a dependency, not permission to unlink.
    for key in keys:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError("Invalid agreement storage reference")
        if db.scalar(
            select(Agreement.id)
            .where(
                Agreement.order_id != order.id,
                or_(
                    Agreement.initial_pdf_key == key,
                    Agreement.returned_pdf_key == key,
                    Agreement.final_pdf_key == key,
                ),
            )
            .limit(1)
        ):
            raise ValueError("Shared agreement storage reference")
        if not db.scalar(
            select(RetentionFileDeletion.id).where(RetentionFileDeletion.file_key == key)
        ):
            db.add(RetentionFileDeletion(file_key=key))
    db.flush()  # Intent and graph removal are committed in the same transaction.
    for model in (
        Notification,
        AgreementFileDeletion,
        Agreement,
        MaterialHandover,
        PaymentRecord,
        DeletionRequest,
        DiskFolder,
        OrderEvent,
    ):
        db.execute(
            delete(model)
            .where(model.order_id == order.id)
            .execution_options(synchronize_session="fetch")
        )
    db.execute(
        delete(Order).where(Order.id == order.id).execution_options(synchronize_session="fetch")
    )


def _drain_files(db: Session, storage: AgreementStorage, limit: int) -> None:
    # No order locks here. Uploads take order -> shared storage lock.
    db.execute(select(func.pg_advisory_xact_lock(STORAGE_LOCK)))
    pending = db.scalars(
        select(RetentionFileDeletion)
        .order_by(
            RetentionFileDeletion.last_attempted_at.asc().nulls_first(), RetentionFileDeletion.id
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for item in pending:
        # Persist failed/skipped attempts too, so one blocked prefix cannot starve later files.
        item.last_attempted_at = datetime.now(UTC)
        try:
            if is_referenced(db, item.file_key):
                continue
            storage.delete(item.file_key)
            db.delete(item)
        except AgreementStorageError:
            logger.error("retention_pdf_cleanup_failed")
    db.commit()


def cleanup_business(
    db: Session,
    storage: AgreementStorage,
    *,
    now: datetime | None = None,
    dry_run: bool = True,
    limit: int = 100,
) -> CleanupResult:
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None or not 1 <= limit <= 10000:
        raise ValueError("Use an aware timestamp and a batch size between 1 and 10000")
    now = now.astimezone(UTC)
    result = CleanupResult()
    ids = db.scalars(
        select(Customer.id)
        .where(Customer.created_at <= now - timedelta(days=14))
        .order_by(Customer.created_at, Customer.id)
    ).all()
    # Read-only selection, then independently locked/rechecked customer transactions.
    # Scan past retained cards, so an old active customer cannot starve later candidates.
    db.rollback()
    processed = 0
    for customer_id in ids:
        if processed >= limit:
            break
        try:
            customer = db.scalar(
                select(Customer).where(Customer.id == customer_id).with_for_update(skip_locked=True)
            )
            if customer is None:
                db.rollback()
                continue
            order_ids = list(db.scalars(select(Order.id).where(Order.customer_id == customer_id)))
            orders = db.scalars(
                select(Order)
                .where(Order.customer_id == customer_id)
                .order_by(Order.id)
                .with_for_update(skip_locked=True)
            ).all()
            deliveries = db.scalars(
                select(Notification)
                .where(
                    or_(
                        Notification.customer_id == customer_id,
                        Notification.order_id.in_(order_ids),
                    )
                )
                .with_for_update(nowait=True)
            ).all()
            if len(orders) != len(order_ids) or any(
                n.status == "processing" and n.lease_until > now for n in deliveries
            ):
                db.rollback()
                continue
            eligible = [o for o in orders if _eligible(db, o, now, unsigned=True)]
            remove_customer = len(eligible) == len(orders)
            if not dry_run:
                for item in eligible:
                    _remove_order(db, item)
                if remove_customer:
                    # Unknown cross-customer actors retain the card through FK checks.
                    for model in (Notification, AuthToken, AuthSession, CustomerEvent):
                        db.execute(
                            delete(model)
                            .where(model.customer_id == customer_id)
                            .execution_options(synchronize_session="fetch")
                        )
                    db.execute(
                        delete(Customer)
                        .where(Customer.id == customer_id)
                        .execution_options(synchronize_session="fetch")
                    )
                db.commit()
            else:
                if not eligible and not remove_customer:
                    db.rollback()
                    continue
                result.candidates.append(
                    {
                        "customer_id": str(customer_id),
                        "order_ids": [str(item.id) for item in eligible],
                        "delete_customer": remove_customer,
                    }
                )
                db.rollback()
            result.orders += len(eligible)
            result.customers += int(remove_customer)
            processed += int(bool(eligible) or remove_customer)
        except Exception:
            db.rollback()
            result.failed += 1
            logger.error("business_retention_customer_failed")
    if not dry_run:
        _drain_files(db, storage, limit)
    result.pending_files = db.scalar(select(func.count()).select_from(RetentionFileDeletion))
    return result
