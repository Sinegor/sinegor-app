from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from sinegor.db.models import (
    AdminUser,
    Agreement,
    AuthToken,
    Customer,
    DeletionRequest,
    DiskFolder,
    MaterialHandover,
    Order,
    OrderEvent,
    PaymentRecord,
    Session,
)
from sinegor.db.types import (
    AgreementStatus,
    DeletionReason,
    DeletionStatus,
    OrderStatus,
    PaymentStatus,
    ServiceType,
    TokenPurpose,
)

pytestmark = pytest.mark.integration
STAMP = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture
def graph(db_session):
    customer = Customer(email=" Client@Example.ru ", created_at=STAMP)
    admin = AdminUser(
        email=" Admin@Example.ru ", password_hash="stored_password_hash", created_at=STAMP
    )
    order = Order(customer=customer, service_type=ServiceType.ANALYSIS, created_at=STAMP)
    db_session.add_all([admin, order])
    db_session.flush()
    return customer, admin, order


def reject(session, obj, constraint):
    with pytest.raises(IntegrityError) as caught:
        with session.begin_nested():
            session.add(obj)
            session.flush()
    assert caught.value.orig.diag.constraint_name == constraint


def test_all_entities_and_relationships_round_trip(db_session, graph):
    customer, admin, order = graph
    second = Order(customer=customer, service_type=ServiceType.TECHNICAL_PREPARATION)
    order.agreed_price = Decimal("12345.67")
    agreement = Agreement(
        order=order,
        status=AgreementStatus.APPROVED,
        final_pdf_key="agreements/signed.pdf",
        final_sha256="a" * 64,
        verified_at=STAMP + timedelta(hours=1),
        verified_by=admin,
        created_at=STAMP,
    )
    folder = DiskFolder(order=order, disk_path="disk:/orders/first", resource_id="resource-1")
    handover = MaterialHandover(order=order)
    payment = PaymentRecord(
        order=order,
        status=PaymentStatus.PAID,
        confirmed_by=admin,
        confirmed_at=STAMP + timedelta(hours=1),
        created_at=STAMP,
    )
    deletion = DeletionRequest(
        order=order,
        reason=DeletionReason.RETENTION_EXPIRED,
        due_at=STAMP + timedelta(days=14),
        created_at=STAMP,
    )
    token = AuthToken(
        customer=customer,
        token_hash="b" * 64,
        purpose=TokenPurpose.INVITATION,
        expires_at=STAMP + timedelta(hours=1),
        created_at=STAMP,
    )
    customer_session = Session(
        customer=customer,
        session_hash="c" * 64,
        expires_at=STAMP + timedelta(days=1),
        created_at=STAMP,
    )
    admin_session = Session(
        admin=admin, session_hash="d" * 64, expires_at=STAMP + timedelta(days=1), created_at=STAMP
    )
    event = OrderEvent(order=order, event_type="order_created", actor_admin=admin)
    db_session.add_all(
        [
            second,
            agreement,
            folder,
            handover,
            payment,
            deletion,
            token,
            customer_session,
            admin_session,
            event,
        ]
    )
    db_session.flush()
    ids = order.id, customer.id, admin.id
    db_session.expire_all()
    loaded = db_session.get(Order, ids[0])
    assert loaded.customer.email == "client@example.ru"
    assert db_session.get(AdminUser, ids[2]).email == "admin@example.ru"
    assert len(loaded.customer.orders) == 2
    assert loaded.number != second.number
    assert loaded.agreed_price == Decimal("12345.67")
    assert loaded.status == OrderStatus.AWAITING_AGREEMENT
    assert loaded.created_at.astimezone(UTC) == STAMP
    assert loaded.agreement.final_sha256 == "a" * 64
    assert loaded.disk_folder.disk_path == "disk:/orders/first"
    assert loaded.material_handover.submitted_at.tzinfo is not None
    assert loaded.payment_record.status == PaymentStatus.PAID
    assert loaded.deletion_request.status == DeletionStatus.WAITING
    assert loaded.events[0].event_type == "order_created"
    assert customer_session.customer.id == ids[1] and customer_session.admin is None
    assert admin_session.admin.id == ids[2] and admin_session.customer is None


@pytest.mark.parametrize("model", [Customer, AdminUser])
def test_normalized_email_unique(db_session, graph, model):
    kwargs = {"email": " CLIENT@example.RU " if model is Customer else " ADMIN@example.RU "}
    if model is AdminUser:
        kwargs["password_hash"] = "another_hash"
    reject(db_session, model(**kwargs), f"uq_{model.__tablename__}_email")


@pytest.mark.parametrize(
    "email",
    ["Mixed@example.ru", " lower@example.ru ", "", "\tclient@example.ru", "client@example.ru\n"],
)
def test_raw_sql_cannot_bypass_email_normalization(db_session, email):
    with pytest.raises(IntegrityError) as caught:
        with db_session.begin_nested():
            db_session.execute(
                text("INSERT INTO customers(id, email) VALUES (:id, :email)"),
                {"id": uuid4(), "email": email},
            )
    assert caught.value.orig.diag.constraint_name == "ck_customers_normalized_email"


def test_orphan_order_rejected(db_session):
    reject(
        db_session,
        Order(customer_id=uuid4(), service_type=ServiceType.ANALYSIS),
        "fk_orders_customer_id_customers",
    )


@pytest.mark.parametrize(
    "model, extra",
    [
        (Agreement, {}),
        (DiskFolder, {"disk_path": "disk:/orders/unique"}),
        (MaterialHandover, {}),
        (PaymentRecord, {}),
        (DeletionRequest, {"reason": DeletionReason.RETENTION_EXPIRED, "due_at": STAMP}),
    ],
)
def test_one_record_per_order_enforced(db_session, graph, model, extra):
    order = graph[2]
    db_session.add(model(order_id=order.id, **extra))
    db_session.flush()
    # Use another path to isolate order uniqueness from path uniqueness.
    values = dict(extra)
    if model is DiskFolder:
        values["disk_path"] = "disk:/orders/different"
    reject(db_session, model(order_id=order.id, **values), f"uq_{model.__tablename__}_order_id")


def test_disk_path_cannot_be_shared_between_orders(db_session, graph):
    customer, _, first = graph
    second = Order(customer=customer, service_type=ServiceType.ANALYSIS)
    db_session.add_all([second, DiskFolder(order=first, disk_path="disk:/orders/shared")])
    db_session.flush()
    reject(
        db_session,
        DiskFolder(order_id=second.id, disk_path="disk:/orders/shared"),
        "uq_disk_folders_disk_path",
    )


@pytest.mark.parametrize("principal", ["neither", "both"])
def test_session_requires_exactly_one_principal(db_session, graph, principal):
    customer, admin, _ = graph
    reject(
        db_session,
        Session(
            customer_id=customer.id if principal == "both" else None,
            admin_id=admin.id if principal == "both" else None,
            session_hash="a" * 64,
            created_at=STAMP,
            expires_at=STAMP + timedelta(hours=1),
        ),
        "ck_sessions_exactly_one_principal",
    )


@pytest.mark.parametrize(
    "model, hash_field", [(AuthToken, "token_hash"), (Session, "session_hash")]
)
def test_only_hashes_are_stored_and_unique(db_session, graph, model, hash_field):
    common = dict(customer_id=graph[0].id, created_at=STAMP, expires_at=STAMP + timedelta(hours=1))
    if model is AuthToken:
        common["purpose"] = TokenPurpose.MAGIC_LINK
    reject(
        db_session,
        model(**common, **{hash_field: "plaintext_secret"}),
        f"ck_{model.__tablename__}_{hash_field}_sha256",
    )
    db_session.add(model(**common, **{hash_field: "a" * 64}))
    db_session.flush()
    reject(
        db_session,
        model(**common, **{hash_field: "a" * 64}),
        f"uq_{model.__tablename__}_{hash_field}",
    )


@pytest.mark.parametrize("model", [AuthToken, Session])
def test_expired_at_creation_rejected(db_session, graph, model):
    values = dict(customer_id=graph[0].id, created_at=STAMP, expires_at=STAMP)
    if model is AuthToken:
        values.update(token_hash="a" * 64, purpose=TokenPurpose.MAGIC_LINK)
    else:
        values["session_hash"] = "a" * 64
    reject(db_session, model(**values), f"ck_{model.__tablename__}_positive_lifetime")


def test_token_use_after_expiry_rejected(db_session, graph):
    reject(
        db_session,
        AuthToken(
            customer_id=graph[0].id,
            token_hash="a" * 64,
            purpose=TokenPurpose.MAGIC_LINK,
            created_at=STAMP,
            expires_at=STAMP + timedelta(minutes=5),
            used_at=STAMP + timedelta(minutes=6),
        ),
        "ck_auth_tokens_used_during_lifetime",
    )


@pytest.mark.parametrize(
    "values, constraint",
    [
        ({"agreed_price": Decimal("-0.01")}, "ck_orders_nonnegative_price"),
        ({"status": OrderStatus.RESULT_READY}, "ck_orders_ready_evidence"),
        ({"status": OrderStatus.CANCELLED}, "ck_orders_closed_status"),
        ({"ready_at": STAMP - timedelta(seconds=1)}, "ck_orders_ready_time"),
        ({"result_notified_at": STAMP}, "ck_orders_notification_time"),
    ],
)
def test_inconsistent_orders_rejected(db_session, graph, values, constraint):
    reject(
        db_session,
        Order(
            customer_id=graph[0].id, service_type=ServiceType.ANALYSIS, created_at=STAMP, **values
        ),
        constraint,
    )


@pytest.mark.parametrize(
    "model, column, check_name, extra",
    [
        (Order, "status", "order_status", {}),
        (Order, "service_type", "service_type", {}),
        (Agreement, "status", "agreement_status", {}),
        (PaymentRecord, "status", "payment_status", {}),
        (
            DeletionRequest,
            "status",
            "deletion_status",
            {
                "reason": DeletionReason.RETENTION_EXPIRED,
                "due_at": STAMP,
            },
        ),
        (
            DeletionRequest,
            "reason",
            "deletion_reason",
            {
                "reason": DeletionReason.RETENTION_EXPIRED,
                "due_at": STAMP,
            },
        ),
        (
            AuthToken,
            "purpose",
            "token_purpose",
            {
                "token_hash": "a" * 64,
                "purpose": TokenPurpose.MAGIC_LINK,
                "created_at": STAMP,
                "expires_at": STAMP + timedelta(hours=1),
            },
        ),
    ],
)
def test_invalid_enum_rejected_by_postgres(db_session, graph, model, column, check_name, extra):
    customer, _, order = graph
    if model is Order:
        record = order
    elif model is AuthToken:
        record = model(customer_id=customer.id, **extra)
    else:
        record = model(order_id=order.id, **extra)
    db_session.add(record)
    db_session.flush()
    # Identifiers come only from the static parametrization above, never user input.
    sql = f"UPDATE {model.__tablename__} SET {column}='bad' WHERE id=:id"
    with pytest.raises(IntegrityError) as caught:
        with db_session.begin_nested():
            db_session.execute(text(sql), {"id": record.id})
    assert caught.value.orig.diag.constraint_name == f"ck_{model.__tablename__}_{check_name}"


def test_agreement_approval_requires_verified_pdf(db_session, graph):
    reject(
        db_session,
        Agreement(order_id=graph[2].id, status=AgreementStatus.APPROVED),
        "ck_agreements_approved_evidence",
    )


def test_paid_record_requires_admin_confirmation(db_session, graph):
    reject(
        db_session,
        PaymentRecord(order_id=graph[2].id, status=PaymentStatus.PAID),
        "ck_payment_records_paid_confirmation",
    )


@pytest.mark.parametrize(
    "values, constraint",
    [
        ({"reason": DeletionReason.EARLY_PERMISSION}, "ck_deletion_requests_early_permission"),
        ({"status": DeletionStatus.CONFIRMED}, "ck_deletion_requests_admin_confirmation"),
        ({"status": DeletionStatus.ERROR}, "ck_deletion_requests_admin_confirmation"),
        ({"status": DeletionStatus.DEFERRED}, "ck_deletion_requests_deferral_evidence"),
    ],
)
def test_deletion_requires_evidence(db_session, graph, values, constraint):
    fields = dict(order_id=graph[2].id, reason=DeletionReason.RETENTION_EXPIRED, due_at=STAMP)
    fields.update(values)
    reject(db_session, DeletionRequest(**fields), constraint)


def test_completed_deletion_requires_confirmation(db_session, graph):
    reject(
        db_session,
        DeletionRequest(
            order_id=graph[2].id,
            reason=DeletionReason.RETENTION_EXPIRED,
            due_at=STAMP,
            status=DeletionStatus.PERFORMED,
            performed_at=STAMP,
        ),
        "ck_deletion_requests_admin_confirmation",
    )


def test_deletion_metadata_does_not_delete_agreement_or_audit(db_session, graph):
    _, admin, order = graph
    agreement = Agreement(
        order=order,
        status=AgreementStatus.APPROVED,
        final_pdf_key="agreements/signed.pdf",
        final_sha256="a" * 64,
        verified_by=admin,
        verified_at=STAMP + timedelta(hours=1),
        created_at=STAMP,
    )
    event = OrderEvent(order=order, event_type="agreement_uploaded", actor_admin=admin)
    folder = DiskFolder(order=order, disk_path="disk:/orders/removal")
    deletion = DeletionRequest(
        order=order,
        reason=DeletionReason.RETENTION_EXPIRED,
        due_at=STAMP,
        status=DeletionStatus.PERFORMED,
        confirmed_at=STAMP,
        confirmed_by=admin,
        performed_at=STAMP,
    )
    db_session.add_all([agreement, event, folder, deletion])
    db_session.flush()
    db_session.delete(folder)
    db_session.flush()
    assert db_session.get(Agreement, agreement.id) is agreement
    assert db_session.get(OrderEvent, event.id) is event
    assert db_session.get(Order, order.id) is order
    # Even loaded children must never be deleted or detached by ORM cascades.
    assert order.agreement is agreement and order.events == [event]
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.delete(order)
            db_session.flush()
    assert db_session.scalar(select(Agreement.id)) == agreement.id
    assert db_session.scalar(select(OrderEvent.id)) == event.id


def test_customer_with_orders_cannot_be_deleted(db_session, graph):
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(delete(Customer).where(Customer.id == graph[0].id))


def test_blank_final_pdf_cannot_be_approved(db_session, graph):
    reject(
        db_session,
        Agreement(
            order_id=graph[2].id,
            status=AgreementStatus.APPROVED,
            final_pdf_key="  ",
            final_sha256="a" * 64,
            verified_by_id=graph[1].id,
            created_at=STAMP,
            verified_at=STAMP + timedelta(hours=1),
        ),
        "ck_agreements_approved_evidence",
    )


def test_ready_and_completed_order_timestamps_round_trip(db_session, graph):
    order = graph[2]
    order.status = OrderStatus.RESULT_READY
    order.ready_at = STAMP + timedelta(hours=1)
    order.result_notified_at = STAMP + timedelta(hours=2)
    db_session.flush()
    order.status = OrderStatus.COMPLETED
    order.closed_at = order.result_notified_at + timedelta(days=14)
    db_session.flush()
    db_session.expire(order)
    assert order.status == OrderStatus.COMPLETED
    assert order.closed_at - order.result_notified_at == timedelta(days=14)


def test_review_nonfinite_price_rejected(db_session, graph):
    reject(
        db_session,
        Order(
            customer_id=graph[0].id, service_type=ServiceType.ANALYSIS, agreed_price=Decimal("NaN")
        ),
        "ck_orders_nonnegative_price",
    )
