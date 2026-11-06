"""No caller-provided strings, URLs, credentials or form contents are accepted."""

from contextvars import ContextVar
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from sinegor.modules.security_events.models import EventType, Reason, Result, SecurityEvent

Actor = tuple[UUID, Literal["admin", "customer"]]

request_identifier: ContextVar[str | None] = ContextVar("security_request_id", default=None)


def record(
    db: Session,
    event_type: EventType,
    reason_code: Reason,
    *,
    result: Result = "success",
    user_id: UUID | None = None,
    user_role: Literal["admin", "customer"] | None = None,
    subject_user_id: UUID | None = None,
) -> None:
    # Successful state changes and their facts share the caller's transaction.
    db.add(
        SecurityEvent(
            event_type=event_type,
            reason_code=reason_code,
            result=result,
            user_id=user_id,
            user_role=user_role,
            subject_user_id=subject_user_id,
            request_id=request_identifier.get()
            or db.info.setdefault("security_request_id", uuid4().hex),
        )
    )


def record_rejection(request: Request, status: int, *, invalid_input: bool = False) -> None:
    """Independent commit survives rollback of a rejected request's transaction."""
    path = request.url.path
    login = path in {"/api/auth/admin/login", "/api/auth/magic-link/verify"}
    reason = getattr(request.state, "security_reason", None)
    if status == 429:
        event_type, reason = "rate_limit", "attempt_limit"
    elif login and (status == 401 or invalid_input):
        event_type, reason = (
            "authentication",
            "invalid_request" if invalid_input else "invalid_credentials",
        )
    elif status in {401, 403} or reason in {"order_not_owned", "agreement_required"}:
        event_type = "access_denied"
        reason = reason or ("authentication_required" if status == 401 else "csrf_failed")
    else:
        return
    principal = getattr(request.state, "security_principal", None)
    with request.app.state.session_factory() as db:
        record(
            db,
            event_type,
            reason,
            result="failure",
            user_id=principal.id if principal else None,
            user_role=principal.role if principal else None,
        )
        db.commit()
