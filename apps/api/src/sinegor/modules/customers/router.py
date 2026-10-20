from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from sinegor.modules.audit.models import CustomerEvent
from sinegor.modules.auth.dependencies import Admin, Database
from sinegor.modules.auth.models import AuthToken, Session
from sinegor.modules.auth.schemas import CustomerRead
from sinegor.modules.customers.models import Customer
from sinegor.modules.customers.schemas import CustomerUpdate
from sinegor.modules.orders.schemas import EventRead

router = APIRouter(prefix="/admin/customers", tags=["customers"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def get_customer(db: Database, customer_id: UUID, *, lock: bool = False) -> Customer:
    statement = select(Customer).where(Customer.id == customer_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    customer = db.scalar(statement)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    return customer


@router.get("", response_model=list[CustomerRead])
def list_customers(principal: Admin, db: Database, limit: Limit = 50, offset: Offset = 0):
    return db.scalars(
        select(Customer).order_by(Customer.created_at, Customer.id).limit(limit).offset(offset)
    ).all()


@router.get("/{customer_id}", response_model=CustomerRead)
def read_customer(customer_id: UUID, principal: Admin, db: Database):
    return get_customer(db, customer_id)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(customer_id: UUID, payload: CustomerUpdate, principal: Admin, db: Database):
    customer = get_customer(db, customer_id, lock=True)
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
    for key, value in changes.items():
        setattr(customer, key, value)
    db.add(
        CustomerEvent(
            customer_id=customer.id, actor_admin_id=principal.id, event_type="customer_updated"
        )
    )
    try:
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
