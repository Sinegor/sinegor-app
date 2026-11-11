from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from sinegor.modules.audit.models import CustomerEvent
from sinegor.modules.auth.dependencies import Admin, Database
from sinegor.modules.auth.models import AuthToken, Session
from sinegor.modules.auth.schemas import CustomerRead
from sinegor.modules.customers.access import change_access
from sinegor.modules.customers.models import Customer
from sinegor.modules.customers.schemas import CustomerBlock, CustomerUpdate
from sinegor.modules.destruction import service as destruction
from sinegor.modules.destruction.metadata import customer_metadata
from sinegor.modules.notifications.service import deliver_from_app
from sinegor.modules.orders.schemas import EventRead
from sinegor.modules.security_events.service import record

router = APIRouter(prefix="/admin/customers", tags=["customers"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def get_customer(db: Database, customer_id: UUID, *, lock: bool = False) -> Customer:
    statement = select(Customer).where(Customer.id == customer_id)
    if lock:
        statement = statement.with_for_update(key_share=True).execution_options(
            populate_existing=True
        )
    customer = db.scalar(statement)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    return customer


@router.get("", response_model=list[CustomerRead])
def list_customers(
    principal: Admin,
    db: Database,
    limit: Limit = 50,
    offset: Offset = 0,
    q: Annotated[str | None, Query(max_length=320)] = None,
):
    statement = select(Customer)
    if q and (query := q.strip()):
        statement = statement.where(
            or_(
                Customer.email.icontains(query, autoescape=True),
                Customer.display_name.icontains(query, autoescape=True),
                Customer.phone.icontains(query, autoescape=True),
            )
        )
    return db.scalars(
        statement.order_by(Customer.created_at.desc(), Customer.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/{customer_id}", response_model=CustomerRead)
def read_customer(customer_id: UUID, principal: Admin, db: Database):
    return get_customer(db, customer_id)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(customer_id: UUID, payload: CustomerUpdate, principal: Admin, db: Database):
    customer = get_customer(db, customer_id, lock=True)
    # Legacy unnamed customers remain usable, but a manual card save must supply a name.
    name = (
        payload.display_name
        if "display_name" in payload.model_fields_set
        else customer.display_name
    )
    if name is None or not name.strip():
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "display_name"),
                    "msg": "Укажите ФИО заказчика.",
                }
            ]
        )
    changes = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if getattr(customer, key) != value
    }
    if not changes:
        return customer
    if "email" in changes:
        # Links and sessions issued for the old identity must no longer grant access.
        db.execute(delete(AuthToken).where(AuthToken.customer_id == customer.id))
        db.execute(
            update(Session)
            .where(Session.customer_id == customer.id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        record(
            db,
            "credential_revoked",
            "email_changed",
            user_id=principal.id,
            user_role="admin",
            subject_user_id=customer.id,
        )
    operation = None
    event_id = uuid4()
    # Only removing an existing phone is partial destruction. FIO remains required.
    if "phone" in changes and changes["phone"] in {None, ""} and customer.phone:
        operation = destruction.prepare(
            db,
            key=f"customer_fields:{customer.id}:{event_id}",
            kind="customer_fields",
            metadata=customer_metadata(
                customer,
                categories=["Номер телефона"],
                entity={"customer_id": str(customer.id), "customer_event_id": str(event_id)},
                source="customers.phone",
                basis=None,
                method="Очистка поля в PostgreSQL",
                initiator=f"admin:{principal.id}",
                executor="FastAPI",
            ),
        )
    for key, value in changes.items():
        setattr(customer, key, value)
    db.add(
        CustomerEvent(
            id=event_id,
            customer_id=customer.id,
            actor_admin_id=principal.id,
            event_type="customer_updated",
        )
    )
    try:
        db.flush()
        if operation is not None:
            destruction.confirm(db, operation)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Customer already exists") from exc
    return customer


@router.get("/{customer_id}/events", response_model=list[EventRead])
def customer_events(
    customer_id: UUID, principal: Admin, db: Database, limit: Limit = 50, offset: Offset = 0
):
    get_customer(db, customer_id)
    return db.scalars(
        select(CustomerEvent)
        .where(CustomerEvent.customer_id == customer_id)
        .order_by(CustomerEvent.created_at, CustomerEvent.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/{customer_id}/block", response_model=CustomerRead)
def block_customer(
    customer_id: UUID,
    payload: CustomerBlock,
    principal: Admin,
    db: Database,
    request: Request,
    tasks: BackgroundTasks,
):
    customer = get_customer(db, customer_id, lock=True)
    identifier = change_access(
        db, customer, principal.id, reason=payload.reason, comment=payload.internal_comment
    )
    if identifier:
        tasks.add_task(deliver_from_app, request.app, identifier)
    return customer


@router.post("/{customer_id}/unblock", response_model=CustomerRead)
def unblock_customer(
    customer_id: UUID, principal: Admin, db: Database, request: Request, tasks: BackgroundTasks
):
    customer = get_customer(db, customer_id, lock=True)
    identifier = change_access(db, customer, principal.id)
    if identifier:
        tasks.add_task(deliver_from_app, request.app, identifier)
    return customer
