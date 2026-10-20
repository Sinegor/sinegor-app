"""Liveness is process-only; readiness verifies PostgreSQL connectivity."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from sinegor.api.errors import error_response

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning(
            "database_unavailable",
            extra={
                "request_id": request.state.request_id,
                "exception_type": type(exc).__name__,
            },
        )
        return error_response(request, 503, "database_unavailable", "Database is unavailable")
    return JSONResponse({"status": "ok", "database": "ok"})
