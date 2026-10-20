from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from sinegor.db.types import OrderStatus, PaymentStatus
from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.auth.dependencies import Admin, Customer, Database, OwnedOrder
from sinegor.modules.customers.router import Limit, Offset, get_customer
from sinegor.modules.orders import service
from sinegor.modules.orders.models import MaterialHandover, Order, PaymentRecord
from sinegor.modules.orders.schemas import (
    EventRead,
    HandoverRead,
    NoteInput,
    OrderCreate,
    OrderRead,
    OrderTerms,
    PaymentRead,
    StatusChange,
)

router = APIRouter(tags=["orders"])


@router.post("/admin/orders", response_model=OrderRead, status_code=201)
def create_order(payload: OrderCreate, principal: Admin, db: Database):
    get_customer(db, payload.customer_id)
    order = Order(**payload.model_dump())
    db.add(order)
    db.flush()
    service.record_event(db, order, "order_created", principal.id)
    db.commit()
    return order


@router.get("/admin/orders", response_model=list[OrderRead])
def list_orders(
    principal: Admin,
    db: Database,
    customer_id: UUID | None = None,
    status: OrderStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    statement = select(Order)
    if customer_id is not None:
        get_customer(db, customer_id)
        statement = statement.where(Order.customer_id == customer_id)
    if status is not None:
        statement = statement.where(Order.status == status)
    return db.scalars(statement.order_by(Order.number).limit(limit).offset(offset)).all()


@router.get("/admin/orders/{order_id}", response_model=OrderRead)
def read_order(order_id: UUID, principal: Admin, db: Database):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


@router.put("/admin/orders/{order_id}/terms", response_model=OrderRead)
def update_terms(order_id: UUID, payload: OrderTerms, principal: Admin, db: Database):
    order = service.locked_order(db, order_id)
    if order.status != OrderStatus.AWAITING_AGREEMENT or order.agreement is not None:
        raise HTTPException(409, "Terms are frozen once an agreement has been issued")
    changes = {
        key: value for key, value in payload.model_dump().items() if getattr(order, key) != value
    }
    if changes:
        for key, value in changes.items():
            setattr(order, key, value)
        service.record_event(db, order, "terms_updated", principal.id)
        db.commit()
    return order


@router.post("/admin/orders/{order_id}/status", response_model=OrderRead)
def change_status(
    order_id: UUID, payload: StatusChange, request: Request, principal: Admin, db: Database
):
    order = service.locked_order(db, order_id)
    try:
        service.transition(
            db, order, payload.status, principal.id, mailer=request.app.state.order_mailer
        )
    except MailDeliveryError as exc:
        raise HTTPException(503, "Result notification failed; order status unchanged") from exc
    db.commit()
    return order


@router.post("/admin/orders/{order_id}/payment", response_model=PaymentRead)
def confirm_payment(order_id: UUID, payload: NoteInput, principal: Admin, db: Database):
    order = service.locked_order(db, order_id)
    payment = order.payment_record
    if payment is not None and payment.status == PaymentStatus.PAID:
        return payment
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(409, "Cancelled orders cannot be marked paid")
    if payment is None:
        payment = PaymentRecord(order_id=order.id)
        db.add(payment)
    payment.status = PaymentStatus.PAID
    payment.confirmed_at = datetime.now(UTC)
    payment.confirmed_by_id = principal.id
    payment.note = payload.note
    service.record_event(db, order, "payment_confirmed", principal.id)
    db.commit()
    return payment


@router.get("/admin/orders/{order_id}/payment", response_model=PaymentRead)
def read_payment(order_id: UUID, principal: Admin, db: Database):
    order = read_order(order_id, principal, db)
    return order.payment_record or PaymentRead(
        status=PaymentStatus.UNPAID, confirmed_at=None, confirmed_by_id=None, note=None
    )


@router.get("/admin/orders/{order_id}/events", response_model=list[EventRead])
def order_events(
    order_id: UUID, principal: Admin, db: Database, limit: Limit = 50, offset: Offset = 0
):
    read_order(order_id, principal, db)
    return db.scalars(
        select(OrderEvent)
        .where(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.created_at, OrderEvent.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/customer/orders/{order_id}/materials", response_model=HandoverRead)
def hand_over_materials(payload: NoteInput, principal: Customer, owned: OwnedOrder, db: Database):
    order = service.locked_order(db, owned.id)
    if order.status not in {OrderStatus.AWAITING_MATERIALS, OrderStatus.IN_PROGRESS}:
        raise HTTPException(409, "Order is not accepting materials")
    service.require_agreement(db, order)
    handover = order.material_handover
    if handover is None:
        handover = MaterialHandover(order_id=order.id, note=payload.note)
        db.add(handover)
        service.record_event(db, order, "materials_submitted", customer_id=principal.id)
        db.commit()
    return handover


@router.get("/admin/orders/{order_id}/materials", response_model=HandoverRead | None)
def read_materials(order_id: UUID, principal: Admin, db: Database):
    return read_order(order_id, principal, db).material_handover
