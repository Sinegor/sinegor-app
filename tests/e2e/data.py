"""Fixture-only bootstrap, clock data and outbox retries; no HTTP business substitutes."""

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from configuration import load_config


def main():
    config = load_config()
    os.environ.update(config["api_env"])
    sys.path.insert(0, str(Path(config["workspace"]) / "apps/api/src"))
    import pyotp
    from cryptography.fernet import Fernet
    from sinegor.core.config import load_settings
    from sinegor.db import models  # noqa: F401
    from sinegor.db.session import create_db_engine, create_session_factory
    from sinegor.modules.agreements.models import Agreement
    from sinegor.modules.audit.models import OrderEvent
    from sinegor.modules.auth.models import AdminUser
    from sinegor.modules.auth.security import HASHER
    from sinegor.modules.notifications.models import Notification
    from sinegor.modules.orders.models import Order
    from sinegor.modules.retention.models import DeletionRequest
    from sqlalchemy import func, select

    settings = load_settings()
    engine = create_db_engine(settings)
    action = sys.argv[1]
    payload = json.load(sys.stdin) if action not in {"bootstrap", "totp"} else {}
    result = {}
    try:
        with create_session_factory(engine)() as db:
            if action == "bootstrap":
                secret = pyotp.random_base32()
                config["admin"]["totp"] = secret
                db.add(
                    AdminUser(
                        email=config["admin"]["email"],
                        password_hash=HASHER.hash(config["admin"]["password"]),
                        totp_secret_encrypted=Fernet(
                            settings.auth_encryption_key.get_secret_value().encode()
                        )
                        .encrypt(secret.encode())
                        .decode(),
                    )
                )
                db.commit()
                path = Path(os.environ["SINEGOR_E2E_CONFIG"])
                path.write_text(json.dumps(config))
                path.chmod(0o600)
                from pypdf import PdfWriter

                for name in ("initial", "signed"):
                    writer = PdfWriter()
                    writer.add_blank_page(width=200, height=200)
                    writer.add_metadata({"/Title": name})
                    with (Path(config["private"]) / f"{name}.pdf").open("wb") as output:
                        writer.write(output)
            elif action == "panel_admin":
                original = db.scalar(
                    select(AdminUser).where(AdminUser.email == config["admin"]["email"])
                )
                email = "delivery-" + config["admin"]["email"]
                if db.scalar(select(AdminUser.id).where(AdminUser.email == email)) is None:
                    db.add(
                        AdminUser(
                            email=email,
                            password_hash=HASHER.hash(config["admin"]["password"]),
                            totp_secret_encrypted=original.totp_secret_encrypted,
                        )
                    )
                    db.commit()
                result = {"email": email}
            elif action == "totp":
                result = {"code": pyotp.TOTP(config["admin"]["totp"]).now()}
            elif action in {"ready_time", "expire_deferral", "inspect"}:
                order = db.get(Order, UUID(payload["order_id"]))
                if order is None:
                    raise RuntimeError("Synthetic order missing")
                if action == "ready_time":
                    now = datetime.now(UTC)
                    order.created_at = now - timedelta(days=16)
                    order.ready_at = now - timedelta(days=14, seconds=payload["seconds_after"])
                    order.result_notified_at = order.ready_at
                    db.commit()
                elif action == "expire_deferral":
                    item = db.scalar(
                        select(DeletionRequest).where(DeletionRequest.order_id == order.id)
                    )
                    item.deferred_until = datetime.now(UTC) - timedelta(minutes=1)
                    db.commit()
                else:
                    agreement = db.scalar(select(Agreement).where(Agreement.order_id == order.id))
                    result = {
                        "status": order.status.value,
                        "agreement_hash": agreement.final_sha256 if agreement else None,
                        "events": db.scalar(
                            select(func.count())
                            .select_from(OrderEvent)
                            .where(OrderEvent.order_id == order.id)
                        ),
                    }
            elif action == "queue_unsent_consultation":
                from sinegor.modules.notifications.service import enqueue

                identifier = enqueue(
                    db,
                    "consultation",
                    recipient="missed-task@example.org",
                    payload={"phone": "+79991234567"},
                )
                enqueue(
                    db, "consultation_telegram", dedup_key=f"consultation_telegram:{identifier}"
                )
                db.commit()
            elif action in {"notifications", "retry_notification"}:
                item = db.scalar(
                    select(Notification)
                    .where(Notification.kind == "consultation")
                    .order_by(Notification.created_at.desc())
                    .limit(1)
                )
                telegram = (
                    db.scalar(
                        select(Notification).where(
                            Notification.dedup_key == f"consultation_telegram:{item.id}"
                        )
                    )
                    if item is not None
                    else None
                )

                def delivery_state(notification):
                    if notification is None:
                        return {"status": "absent", "attempts": 0}
                    return {
                        "status": notification.status,
                        "attempts": notification.attempts,
                        "retry_in_seconds": (
                            notification.available_at - datetime.now(UTC)
                        ).total_seconds(),
                        "contacts_retained": notification.recipient is not None
                        and bool(notification.payload.get("phone")),
                        "contact_cleared": notification.recipient is None
                        and notification.payload == {},
                    }

                if action == "notifications":
                    result = {
                        "smtp": delivery_state(item),
                        "telegram": delivery_state(telegram),
                    }
                else:
                    channel = payload.get("channel", "smtp")
                    if channel not in {"smtp", "telegram"}:
                        raise RuntimeError("Unsupported E2E notification channel")
                    notification = item if channel == "smtp" else telegram
                    if notification is None or notification.status != "pending":
                        raise RuntimeError("Expected a pending synthetic consultation channel")
                    notification.available_at = datetime.now(UTC) - timedelta(seconds=1)
                    db.commit()
            elif action == "age_result_notification":
                item = db.scalar(
                    select(Notification).where(
                        Notification.order_id == UUID(payload["order_id"]),
                        Notification.kind == "result_ready",
                        Notification.status == "pending",
                    )
                )
                if item is None:
                    raise RuntimeError("Expected a pending synthetic readiness notification")
                item.created_at = datetime.now(UTC) - timedelta(hours=24)
                db.commit()
            elif action == "job":
                # Use the real CLI, in an independent interpreter with the same isolated settings.
                import subprocess

                names = {"process_orders", "process_notifications"}
                if payload["name"] not in names:
                    raise RuntimeError("Unsupported E2E job")
                process = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).with_name("api.py")),
                        "--job",
                        payload["name"],
                    ],
                    env=config["api_env"]
                    | {"SINEGOR_E2E_CONFIG": os.environ["SINEGOR_E2E_CONFIG"]},
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                if process.returncode:
                    raise RuntimeError("Synthetic job failed")
            else:
                raise RuntimeError("Unsupported E2E data operation")
    finally:
        engine.dispose()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Driver errors may contain SQL parameters: do not print them or their traceback.
        print("E2E fixture operation failed", file=sys.stderr)
        raise SystemExit(1) from None
