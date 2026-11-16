"""Read-only run/queue diagnostics; never return contact data, payload or SQL errors."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, text

from sinegor.core.config import load_settings
from sinegor.core.logging import configure_logging
from sinegor.db import models  # noqa: F401
from sinegor.db.session import create_db_engine
from sinegor.db.types import AgreementStatus, DeletionStatus, OrderStatus
from sinegor.jobs.runtime import SCHEDULED_JOBS, read_state
from sinegor.modules.agreements.models import Agreement, AgreementFileDeletion
from sinegor.modules.auth.models import AuthToken, Session
from sinegor.modules.destruction.models import DestructionOperation
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications.models import Notification
from sinegor.modules.notifications.retry import deadline_expression
from sinegor.modules.orders.models import Order
from sinegor.modules.retention.models import DeletionRequest, RetentionFileDeletion

MAX_AGES = {name: 90000 for name in SCHEDULED_JOBS} | {
    "process_orders": 900,
    "process_notifications": 900,
    "cleanup_agreements": 1800,
}


def evaluate_state(state: dict, *, now: datetime, max_age: int) -> dict:
    result = {"issues": []}
    try:
        for key in ("started_at", "finished_at", "last_success_at"):
            value = state.get(key)
            value = datetime.fromisoformat(value) if value is not None else None
            if value is not None and (value.tzinfo is None or value > now):
                raise ValueError
            result[key] = value.isoformat() if value else None
        started = datetime.fromisoformat(result["started_at"])
        status = state["status"]
        if status not in ("running", "success", "failed"):
            raise ValueError
        result["status"] = status
        if status == "failed":
            result["issues"].append("run_failed")
        if status == "running" and (now - started).total_seconds() > 900:
            result["issues"].append("run_stuck")
        success = result["last_success_at"]
        if success is None:
            if status != "running" or (now - started).total_seconds() > 900:
                result["issues"].append("never_succeeded")
        elif (now - datetime.fromisoformat(success)).total_seconds() > max_age:
            result["issues"].append("run_stale")
        code, duration = state.get("exit_code"), state.get("duration_ms")
        if code not in (None, 0, 1) or (
            duration is not None and (type(duration) not in (int, float) or duration < 0)
        ):
            raise ValueError
        if status == "success" and (code != 0 or result["finished_at"] is None):
            raise ValueError
        result.update(exit_code=code, duration_ms=duration)
        return result
    except (ValueError, TypeError, KeyError):
        return {"issues": ["invalid_state"]}


def queue_metrics(connection, *, now: datetime) -> dict[str, int]:
    late = now - timedelta(minutes=15)
    pending = Notification.status == "pending"
    stale = (Notification.status == "processing") & (Notification.lease_until <= now)
    eligible = (pending | stale) & (
        (Notification.available_at <= now) | (deadline_expression() <= now)
    )
    expressions = {
        "notifications_total": True,
        "notifications_ready": eligible,
        "notifications_late_ready": eligible
        & ((Notification.available_at <= late) | (deadline_expression() <= now)),
        "notifications_late_unattempted": eligible
        & (Notification.attempts == 0)
        & (Notification.created_at <= late),
        "notifications_past_deadline": (pending | stale) & (deadline_expression() <= now),
        "notifications_stale_leases": stale,
        "notifications_failed": Notification.status == "failed",
        "notifications_expired": Notification.status == "expired",
    }
    row = (
        connection.execute(
            select(
                *[
                    func.count().filter(condition).label(name)
                    for name, condition in expressions.items()
                ]
            ).select_from(Notification)
        )
        .mappings()
        .one()
    )
    result = {key: int(value) for key, value in row.items()}

    def count(model, condition):
        return int(connection.scalar(select(func.count()).select_from(model).where(condition)))

    result["agreement_file_deletions"] = count(AgreementFileDeletion, True)
    result["agreement_file_deletions_late"] = count(
        AgreementFileDeletion, AgreementFileDeletion.created_at <= now - timedelta(minutes=20)
    )
    result["retention_file_deletions"] = count(RetentionFileDeletion, True)
    result["retention_file_deletions_late"] = count(
        RetentionFileDeletion, RetentionFileDeletion.created_at <= now - timedelta(hours=25)
    )
    documents = (
        DestructionOperation.destroyed_at.is_not(None)
        & (DestructionOperation.state != "ready")
        & (DestructionOperation.expires_at > now)
    )
    result["destruction_documents_pending"] = count(DestructionOperation, documents)
    result["destruction_documents_late"] = count(
        DestructionOperation, documents & (DestructionOperation.destroyed_at <= late)
    )
    result["auth_tokens_expired"] = count(AuthToken, AuthToken.expires_at < now)
    result["auth_sessions_expired"] = count(Session, Session.expires_at < now)
    result["order_transitions_late"] = count(
        Order,
        or_(
            (Order.status == OrderStatus.RESULT_READY)
            & (Order.result_notified_at <= late - timedelta(days=14)),
            (Order.status == OrderStatus.AWAITING_AGREEMENT)
            & select(Agreement.id)
            .where(
                Agreement.order_id == Order.id,
                Agreement.status == AgreementStatus.APPROVED,
                Agreement.verified_at <= late,
            )
            .exists(),
        ),
    )
    result["deletion_requests_missing_late"] = count(
        Order,
        Order.status.in_([OrderStatus.RESULT_READY, OrderStatus.COMPLETED])
        & (Order.result_notified_at <= late - timedelta(days=14))
        & ~select(DeletionRequest.id).where(DeletionRequest.order_id == Order.id).exists()
        & ~select(DiskFolder.id)
        .where(DiskFolder.order_id == Order.id, DiskFolder.deleted_at.is_not(None))
        .exists(),
    )
    result["deletion_deferrals_late"] = count(
        DeletionRequest,
        (DeletionRequest.status == DeletionStatus.DEFERRED)
        & (DeletionRequest.deferred_until <= late)
        & (DeletionRequest.due_at <= late),
    )
    return result


def snapshot(settings, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    states, issues = {}, []
    for name in SCHEDULED_JOBS:
        try:
            state = evaluate_state(
                read_state(settings.agreement_storage_dir, name), now=now, max_age=MAX_AGES[name]
            )
        except FileNotFoundError:
            state = {"issues": ["state_missing"]}
        except Exception:
            state = {"issues": ["state_unreadable"]}
        states[name] = state
        issues.extend(f"{name}:{reason}" for reason in state["issues"])
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            metrics = queue_metrics(connection, now=now)
    finally:
        engine.dispose()
    actionable = (
        "notifications_late_ready",
        "notifications_late_unattempted",
        "notifications_past_deadline",
        "notifications_stale_leases",
        "notifications_failed",
        "notifications_expired",
        "agreement_file_deletions_late",
        "retention_file_deletions_late",
        "destruction_documents_late",
        "order_transitions_late",
        "deletion_requests_missing_late",
        "deletion_deferrals_late",
    )
    issues.extend(key for key in actionable if metrics[key])
    return {
        "event": "jobs_status",
        "observed_at": now.isoformat(),
        "status": "critical" if issues else "ok",
        "issues": issues,
        "jobs": states,
        "queues": metrics,
    }


def main() -> int:
    configure_logging("INFO")
    try:
        result = snapshot(load_settings())
    except Exception as exc:
        result = {
            "event": "jobs_status",
            "status": "critical",
            "issues": ["status_check_failed"],
            "error_type": type(exc).__name__,
        }
    print(json.dumps(result))
    return int(result["status"] != "ok")


if __name__ == "__main__":
    raise SystemExit(main())
