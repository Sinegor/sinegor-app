from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from sinegor.db.types import DeletionStatus
from sinegor.modules.auth.dependencies import Admin, Customer, Database, OwnedOrder
from sinegor.modules.customers.router import Limit, Offset
from sinegor.modules.orders.models import Order
from sinegor.modules.retention import service
from sinegor.modules.retention.models import DeletionRequest
from sinegor.modules.retention.schemas import (
    Confirmation,
    ConfirmDeletion,
    CustomerDeletionRead,
    DeferDeletion,
    DeletionRead,
)

router = APIRouter(tags=["retention"])


@router.get("/admin/deletion-requests", response_model=list[DeletionRead])
def list_requests(
    principal: Admin,
    db: Database,
    status: DeletionStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    statement = select(DeletionRequest)
    if status is not None:
        statement = statement.where(DeletionRequest.status == status)
    return db.scalars(
        statement.order_by(DeletionRequest.due_at, DeletionRequest.id).limit(limit).offset(offset)
    ).all()


@router.get("/admin/orders/{order_id}/deletion-request", response_model=DeletionRead | None)
def read_admin_request(order_id: UUID, principal: Admin, db: Database):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return service.request_for(db, order)


@router.get(
    "/customer/orders/{order_id}/deletion-request", response_model=CustomerDeletionRead | None
)
def read_customer_request(principal: Customer, owned: OwnedOrder, db: Database):
    return service.request_for(db, owned)


@router.post("/customer/orders/{order_id}/deletion-permission", response_model=CustomerDeletionRead)
def authorize_early(payload: Confirmation, principal: Customer, owned: OwnedOrder, db: Database):
    return service.authorize_early(db, owned.id, principal.id)


@router.post("/admin/orders/{order_id}/deletion-request/confirm", response_model=DeletionRead)
def confirm(order_id: UUID, payload: ConfirmDeletion, principal: Admin, db: Database):
    return service.confirm(db, order_id, payload.deletion_request_id, principal.id)


@router.post("/admin/orders/{order_id}/deletion-request/defer", response_model=DeletionRead)
def defer(order_id: UUID, payload: DeferDeletion, principal: Admin, db: Database):
    return service.defer(
        db,
        order_id,
        payload.deletion_request_id,
        principal.id,
        payload.deferred_until,
        payload.note,
    )
