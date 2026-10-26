from fastapi import APIRouter, BackgroundTasks, Request

from sinegor.modules.auth.dependencies import Database
from sinegor.modules.auth.router import throttle
from sinegor.modules.notifications.schemas import ConsultationInput
from sinegor.modules.notifications.service import deliver_from_app, enqueue

router = APIRouter(tags=["notifications"])


@router.post("/consultations", status_code=202)
def request_consultation(
    payload: ConsultationInput, request: Request, db: Database, tasks: BackgroundTasks
):
    throttle(request, db, "consultation", str(payload.email))
    identifier = enqueue(
        db, "consultation", recipient=str(payload.email), payload={"phone": payload.phone}
    )
    db.commit()
    tasks.add_task(deliver_from_app, request.app, identifier)
    return {"message": "Consultation request accepted"}
