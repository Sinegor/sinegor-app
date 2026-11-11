"""Explicit expired business-graph removal with durable, private file retries.

No Disk API calls and no security journal privileges.
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
from sinegor.modules.destruction import service as destruction
from sinegor.modules.destruction.metadata import customer_metadata
from sinegor.modules.destruction.models import DestructionOperation
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


def _business_metadata(customer: Customer, categories: list[str], entity: dict, basis: str) -> dict:
    return customer_metadata(
        customer,
        categories=categories,
        entity=entity,
        source="business_retention",
        basis=basis,
        method=(
            "Удаление записей PostgreSQL и файлов соглашения на сервере"
            if "agreement_id" in entity
            else "Удаление записей PostgreSQL"
        ),
        initiator="scheduler",
        executor="FastAPI business retention",
    )


def _remove_order(db: Session, order: Order, customer: Customer) -> None:
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
    signed = agreement is not None and (
        agreement.status == AgreementStatus.APPROVED or agreement.final_pdf_key is not None
    )
    basis = (
        "Истечение пятилетнего срока хранения соглашения и истории заказа"
        if signed
        else "Истечение срока хранения карточки без подписанных соглашений"
    )
    entity = {"order_id": str(order.id), "customer_id": str(customer.id)}
    agreement_operation = None
    if signed:
        agreement_operation = destruction.prepare(
            db,
            key=f"agreement:{agreement.id}",
            kind="agreement",
            metadata=_business_metadata(
                customer,
                ["Данные окончательного подписанного соглашения", "PDF соглашения"],
                {**entity, "agreement_id": str(agreement.id)},
                basis,
            ),
        )
    categories = ["История заказа"]
    for model, category in (
        (OrderEvent, "События заказа"),
        (DeletionRequest, "Записи об удалении материалов"),
        (DiskFolder, "Сведения о папке заказа"),
        (MaterialHandover, "Сведения о передаче материалов"),
        (PaymentRecord, "Сведения об оплате"),
        (Notification, "Сведения уведомлений по заказу"),
    ):
        if db.scalar(select(model.id).where(model.order_id == order.id).limit(1)):
            categories.append(category)
    history_operation = destruction.prepare(
        db,
        key=f"order_history:{order.id}",
        kind="order_history",
        metadata=_business_metadata(customer, categories, entity, basis),
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
        intent = db.scalar(
            select(RetentionFileDeletion).where(RetentionFileDeletion.file_key == key)
        )
        if intent is None:
            db.add(
                RetentionFileDeletion(
                    file_key=key,
                    operation_id=agreement_operation.id if agreement_operation else None,
                )
            )
        elif agreement_operation is not None:
            if intent.operation_id not in {None, agreement_operation.id}:
                raise ValueError("Shared agreement deletion intent")
            intent.operation_id = agreement_operation.id
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
    db.flush()
    destruction.confirm(db, history_operation)
    if agreement_operation is not None and not keys:
        destruction.confirm(db, agreement_operation)


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
            operation_id = item.operation_id
            db.delete(item)
            db.flush()
            if operation_id and not db.scalar(
                select(RetentionFileDeletion.id)
                .where(RetentionFileDeletion.operation_id == operation_id)
                .limit(1)
            ):
                operation = db.get(DestructionOperation, operation_id)
                if operation is not None:
                    destruction.confirm(db, operation)
        except AgreementStorageError:
            if item.operation_id:
                operation = db.get(DestructionOperation, item.operation_id)
                if operation is not None:
                    destruction.mark_error(operation, "agreement_pdf_cleanup_failed")
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
                    _remove_order(db, item, customer)
                if remove_customer:
                    categories = ["Адрес электронной почты"]
                    if customer.display_name:
                        categories.append("ФИО")
                    if customer.phone:
                        categories.append("Номер телефона")
                    if customer.blocked_at is not None:
                        categories.append("Сведения об ограничении доступа")
                    for model, category in (
                        (CustomerEvent, "События карточки заказчика"),
                        (AuthToken, "Сведения токенов авторизации"),
                        (AuthSession, "Сведения сессий авторизации"),
                        (Notification, "Сведения уведомлений заказчика"),
                    ):
                        if db.scalar(
                            select(model.id).where(model.customer_id == customer_id).limit(1)
                        ):
                            categories.append(category)
                    customer_operation = destruction.prepare(
                        db,
                        key=f"customer:{customer.id}",
                        kind="customer",
                        metadata=_business_metadata(
                            customer,
                            categories,
                            {"customer_id": str(customer_id)},
                            "Истечение срока хранения карточки заказчика",
                        ),
                    )
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
                    db.flush()
                    destruction.confirm(db, customer_operation)
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
