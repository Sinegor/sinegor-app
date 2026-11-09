from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Request

from sinegor.modules.auth.dependencies import Admin, Database
from sinegor.modules.auth.router import throttle
from sinegor.modules.notifications.consultations import (
    handle_consultation,
    list_consultations,
    retry_consultation,
)
from sinegor.modules.notifications.problems import list_delivery_problems
from sinegor.modules.notifications.schemas import (
    ConsultationConfirmation,
    ConsultationInput,
    ConsultationRead,
    ConsultationRetry,
    DeliveryProblem,
    DeliverySummary,
)
from sinegor.modules.notifications.service import deliver_from_app, delivery_summary, enqueue

router = APIRouter(tags=["notifications"])


@router.post("/consultations", status_code=202)
def request_consultation(
    payload: ConsultationInput, request: Request, db: Database, tasks: BackgroundTasks
):
    throttle(request, db, "consultation", str(payload.email))
    identifier = enqueue(
        db, "consultation", recipient=str(payload.email), payload={"phone": payload.phone}
    )
    telegram_identifier = enqueue(
        db, "consultation_telegram", dedup_key=f"consultation_telegram:{identifier}"
    )
    db.commit()
    tasks.add_task(deliver_from_app, request.app, identifier)
    tasks.add_task(deliver_from_app, request.app, telegram_identifier)
    return {"message": "Consultation request accepted"}


@router.get("/admin/notifications/summary", response_model=list[DeliverySummary])
def read_delivery_summary(principal: Admin, db: Database):
    return delivery_summary(db)


@router.get("/admin/notifications/problems", response_model=list[DeliveryProblem])
def read_delivery_problems(
    principal: Admin,
    db: Database,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_delivery_problems(db, limit=limit, offset=offset)


@router.get("/admin/consultations", response_model=list[ConsultationRead])
def read_consultations(
    principal: Admin,
    db: Database,
    view: Literal["active", "handled"] = "active",
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_consultations(db, view=view, limit=limit, offset=offset)


@router.post("/admin/consultations/{identifier}/retry", status_code=202)
def retry_consultation_delivery(
    identifier: UUID,
    payload: ConsultationRetry,
    principal: Admin,
    db: Database,
    request: Request,
    tasks: BackgroundTasks,
):
    job_id = retry_consultation(db, identifier, payload.channel)
    tasks.add_task(deliver_from_app, request.app, job_id)
    return {"message": "Delivery retry requested"}


@router.post("/admin/consultations/{identifier}/handle")
def mark_consultation_handled(
    identifier: UUID, payload: ConsultationConfirmation, principal: Admin, db: Database
):
    handle_consultation(db, identifier)
    return {"message": "Consultation handled"}
