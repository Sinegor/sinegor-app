import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session as DBSession

from sinegor.core.config import Settings
from sinegor.db.types import TokenPurpose
from sinegor.integrations.email.smtp import AuthMailer, MailDeliveryError
from sinegor.modules.auth.models import AdminUser, AuthToken, Session
from sinegor.modules.auth.security import (
    DUMMY_HASH,
    HASHER,
    matched_totp_step,
    new_secret,
    secret_hash,
    verify_password,
)
from sinegor.modules.customers.models import Customer

logger = logging.getLogger(__name__)


def issue_and_send_link(
    db: DBSession, settings: Settings, mailer: AuthMailer, customer: Customer, purpose: TokenPurpose
) -> None:
    # Capture earlier links under the customer lock; preserve them until SMTP succeeds.
    db.scalar(select(Customer).where(Customer.id == customer.id).with_for_update())
    previous_ids = list(
        db.scalars(
            select(AuthToken.id).where(
                AuthToken.customer_id == customer.id, AuthToken.used_at.is_(None)
            )
        )
    )
    now = datetime.now(UTC)
    raw = new_secret()
    token = AuthToken(
        customer_id=customer.id,
        token_hash=secret_hash(raw),
        purpose=purpose,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.magic_link_ttl_seconds),
    )
    db.add(token)
    db.commit()
    try:
        # Fragment is never sent to HTTP servers or proxy logs. Frontend will POST it explicitly.
        link = str(settings.public_origin).rstrip("/") + "/auth/magic-link#token=" + raw
        mailer.send_login_link(customer.email, link)
    except MailDeliveryError:
        db.execute(delete(AuthToken).where(AuthToken.id == token.id, AuthToken.used_at.is_(None)))
        db.commit()
        logger.error("auth_email_failed")
        raise
    if previous_ids:
        # A concurrent send may have issued a newer link; do not revoke that link.
        db.execute(
            delete(AuthToken).where(AuthToken.id.in_(previous_ids), AuthToken.used_at.is_(None))
        )
        db.commit()


def deliver_requested_link(app, email: str) -> None:
    # Runs after the uniform 202 response; existence and SMTP latency are not exposed in response.
    with app.state.session_factory() as db:
        try:
            customer = db.scalar(select(Customer).where(Customer.email == email))
            if customer is not None:
                issue_and_send_link(
                    db, app.state.settings, app.state.auth_mailer, customer, TokenPurpose.MAGIC_LINK
                )
        except MailDeliveryError:
            pass  # already logged without recipient, URL or message contents
        except Exception as exc:
            db.rollback()
            logger.error("auth_link_request_failed", extra={"exception_type": type(exc).__name__})


def create_session(
    db: DBSession, settings: Settings, old_cookie: str, *, customer_id=None, admin_id=None
) -> str:
    now = datetime.now(UTC)
    if old_cookie:
        db.execute(
            update(Session)
            .where(Session.session_hash == secret_hash(old_cookie), Session.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    raw = new_secret()
    ttl = (
        settings.admin_session_ttl_seconds if admin_id is not None else settings.session_ttl_seconds
    )
    db.add(
        Session(
            session_hash=secret_hash(raw),
            customer_id=customer_id,
            admin_id=admin_id,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
    )
    db.commit()
    return raw


def consume_link(db: DBSession, settings: Settings, token: str, old_cookie: str) -> str:
    now = datetime.now(UTC)
    # UPDATE is atomic: concurrent requests cannot consume the same credential twice.
    customer_id = db.scalar(
        update(AuthToken)
        .where(
            AuthToken.token_hash == secret_hash(token),
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
            AuthToken.purpose.in_([TokenPurpose.INVITATION, TokenPurpose.MAGIC_LINK]),
        )
        .values(used_at=now)
        .returning(AuthToken.customer_id)
    )
    if customer_id is None:
        raise HTTPException(401, "Invalid or expired credentials")
    return create_session(db, settings, old_cookie, customer_id=customer_id)


def admin_login(
    db: DBSession, settings: Settings, email: str, password: str, code: str, old_cookie: str
) -> str:
    admin = db.scalar(select(AdminUser).where(AdminUser.email == email))
    password_ok = verify_password(password, admin.password_hash if admin else DUMMY_HASH)
    if not password_ok or admin is None or not admin.is_active or not admin.totp_secret_encrypted:
        raise HTTPException(401, "Invalid or expired credentials")
    key = settings.auth_encryption_key
    step = matched_totp_step(
        admin.totp_secret_encrypted,
        key.get_secret_value() if key else "",
        code,
        datetime.now(UTC).timestamp(),
    )
    if step is None:
        raise HTTPException(401, "Invalid or expired credentials")
    claimed = db.scalar(
        update(AdminUser)
        .where(
            AdminUser.id == admin.id,
            or_(AdminUser.last_totp_step.is_(None), AdminUser.last_totp_step < step),
        )
        .values(last_totp_step=step)
        .returning(AdminUser.id)
    )
    if claimed is None:
        raise HTTPException(401, "Invalid or expired credentials")
    if HASHER.check_needs_rehash(admin.password_hash):
        admin.password_hash = HASHER.hash(password)
    return create_session(db, settings, old_cookie, admin_id=admin.id)


def provision_admin(
    db: DBSession, settings: Settings, email: str, password: str, totp_secret: str, code: str
) -> AdminUser:
    from cryptography.fernet import Fernet

    from sinegor.modules.auth.schemas import EmailInput

    if settings.auth_encryption_key is None:
        raise ValueError("Configure AUTH_ENCRYPTION_KEY before creating an administrator")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12 to 128 characters")
    key = settings.auth_encryption_key.get_secret_value()
    encrypted = Fernet(key.encode()).encrypt(totp_secret.encode()).decode()
    step = matched_totp_step(encrypted, key, code, datetime.now(UTC).timestamp())
    if step is None:
        raise ValueError("Authenticator code is invalid")
    admin = AdminUser(
        email=str(EmailInput(email=email).email),
        password_hash=HASHER.hash(password),
        totp_secret_encrypted=encrypted,
        last_totp_step=step,
    )
    db.add(admin)
    db.commit()
    return admin
