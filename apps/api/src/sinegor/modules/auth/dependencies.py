"""Authentication, roles and ownership are checked on the backend."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from sinegor.db.session import get_session
from sinegor.modules.auth.models import Session
from sinegor.modules.auth.security import secret_hash
from sinegor.modules.orders.models import Order

Database = Annotated[DBSession, Depends(get_session)]


@dataclass(frozen=True)
class Principal:
    id: UUID
    role: Literal["customer", "admin"]
    email: str
    session_id: UUID
    expires_at: datetime


def current_principal(request: Request, db: Database) -> Principal:
    raw = request.cookies.get(request.app.state.settings.session_cookie_name, "")
    if len(raw) != 43:
        raise HTTPException(401, "Authentication required")
    session = db.scalar(
        select(Session).where(
            Session.session_hash == secret_hash(raw),
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
    )
    if session is None:
        raise HTTPException(401, "Authentication required")
    if session.admin_id is not None:
        if session.admin is None or not session.admin.is_active:
            raise HTTPException(401, "Authentication required")
        return Principal(
            session.admin_id, "admin", session.admin.email, session.id, session.expires_at
        )
    if session.customer is None:
        raise HTTPException(401, "Authentication required")
    return Principal(
        session.customer_id, "customer", session.customer.email, session.id, session.expires_at
    )


Authenticated = Annotated[Principal, Depends(current_principal)]


def require_admin(principal: Authenticated) -> Principal:
    if principal.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return principal


def require_customer(principal: Authenticated) -> Principal:
    if principal.role != "customer":
        raise HTTPException(403, "Customer access required")
    return principal


Admin = Annotated[Principal, Depends(require_admin)]
Customer = Annotated[Principal, Depends(require_customer)]


def owned_order(order_id: UUID, principal: Customer, db: Database) -> Order:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.customer_id == principal.id))
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


OwnedOrder = Annotated[Order, Depends(owned_order)]
