from fastapi import APIRouter, Request

from sinegor.modules.analytics.schemas import ConsentInput, ConsentReceipt
from sinegor.modules.analytics.service import record_event
from sinegor.modules.auth.dependencies import Database
from sinegor.modules.auth.router import throttle

router = APIRouter(tags=["analytics"])


@router.post("/analytics/consent", response_model=ConsentReceipt)
def write_consent(payload: ConsentInput, request: Request, db: Database):
    # The shared limiter stores only HMAC bucket keys. No IP is stored in this journal.
    # A browser can rotate its pseudonym; the separate IP limit still bounds writes.
    throttle(request, db, "analytics_consent", str(payload.browser_id))
    return record_event(db, payload)
