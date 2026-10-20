from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from sinegor.db.types import TokenPurpose
from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.modules.auth import service
from sinegor.modules.auth.dependencies import Admin, Authenticated, Customer, Database, OwnedOrder
from sinegor.modules.auth.models import Session
from sinegor.modules.auth.rate_limit import enforce_rate_limit
from sinegor.modules.auth.schemas import (
    AdminLogin,
    CustomerCreate,
    CustomerRead,
    EmailInput,
    MagicLinkInput,
    OrderAccessRead,
    PrincipalRead,
)
from sinegor.modules.auth.security import csrf_token, valid_csrf
from sinegor.modules.customers.models import Customer as CustomerModel
from sinegor.modules.orders.models import Order

router = APIRouter(tags=["auth"])


def throttle(request: Request, db: Database, scope: str, identity: str | None = None):
    enforce_rate_limit(
        db,
        request.app.state.settings,
        request.app.state.csrf_key,
        scope,
        request.client.host if request.client else "unknown",
        identity,
    )


def session_cookie(request: Request) -> str:
    return request.cookies.get(request.app.state.settings.session_cookie_name, "")


def set_login_cookie(request: Request, response: Response, raw: str, admin: bool = False):
    settings = request.app.state.settings
    ttl = settings.admin_session_ttl_seconds if admin else settings.session_ttl_seconds
    response.set_cookie(
        settings.session_cookie_name,
        raw,
        max_age=ttl,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="strict",
        path="/",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.app_env == "production",
        httponly=True,
        samesite="strict",
    )


@router.get("/auth/csrf")
def get_csrf(request: Request, response: Response):
    settings = request.app.state.settings
    existing = request.cookies.get(settings.csrf_cookie_name, "")
    if valid_csrf(
        existing, request.app.state.csrf_key, session_cookie(request), settings.csrf_ttl_seconds
    ):
        return {"csrf_token": existing}
    token = csrf_token(request.app.state.csrf_key, session_cookie(request))
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="strict",
        path="/",
        max_age=settings.csrf_ttl_seconds,
    )
    return {"csrf_token": token}


@router.post("/auth/magic-link/request", status_code=202)
def request_magic_link(payload: EmailInput, request: Request, db: Database, tasks: BackgroundTasks):
    throttle(request, db, "magic_request", str(payload.email))
    tasks.add_task(service.deliver_requested_link, request.app, str(payload.email))
    return {"message": "If access is available, a sign-in email will be sent"}


@router.post("/auth/magic-link/verify", status_code=204)
def verify_magic_link(payload: MagicLinkInput, request: Request, response: Response, db: Database):
    throttle(request, db, "magic_verify")
    raw = service.consume_link(
        db, request.app.state.settings, payload.token, session_cookie(request)
    )
    set_login_cookie(request, response, raw)


@router.post("/auth/admin/login", status_code=204)
def login_admin(payload: AdminLogin, request: Request, response: Response, db: Database):
    throttle(request, db, "admin_login", str(payload.email))
    raw = service.admin_login(
        db,
        request.app.state.settings,
        str(payload.email),
        payload.password.get_secret_value(),
        payload.code,
        session_cookie(request),
    )
    set_login_cookie(request, response, raw, admin=True)


@router.get("/auth/session", response_model=PrincipalRead)
def read_session(principal: Authenticated):
    return principal


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, principal: Authenticated, db: Database):
    db.execute(
        update(Session)
        .where(Session.id == principal.session_id)
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()
    settings = request.app.state.settings
    for cookie in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(
            cookie,
            path="/",
            secure=settings.app_env == "production",
            httponly=True,
            samesite="strict",
        )


@router.post("/admin/customers", response_model=CustomerRead, status_code=201)
def create_customer(payload: CustomerCreate, request: Request, principal: Admin, db: Database):
    customer = CustomerModel(**payload.model_dump())
    db.add(customer)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Customer already exists") from exc
    try:
        service.issue_and_send_link(
            db,
            request.app.state.settings,
            request.app.state.auth_mailer,
            customer,
            TokenPurpose.INVITATION,
        )
    except MailDeliveryError as exc:
        raise HTTPException(
            503,
            "Customer saved; invitation failed. Retry invitation",
            headers={"X-Customer-ID": str(customer.id)},
        ) from exc
    return customer


@router.post("/admin/customers/{customer_id}/invite", status_code=202)
def invite_customer(customer_id: UUID, request: Request, principal: Admin, db: Database):
    throttle(request, db, "invitation", str(customer_id))
    customer = db.get(CustomerModel, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    try:
        service.issue_and_send_link(
            db,
            request.app.state.settings,
            request.app.state.auth_mailer,
            customer,
            TokenPurpose.INVITATION,
        )
    except MailDeliveryError as exc:
        raise HTTPException(503, "Invitation delivery failed") from exc
    return {"message": "Invitation submitted to SMTP"}


@router.get("/customer/orders", response_model=list[OrderAccessRead])
def customer_orders(principal: Customer, db: Database):
    return db.scalars(
        select(Order).where(Order.customer_id == principal.id).order_by(Order.number)
    ).all()


@router.get("/customer/orders/{order_id}", response_model=OrderAccessRead)
def customer_order(order: OwnedOrder):
    return order
