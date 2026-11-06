"""Consistent JSON errors without request bodies or exception internals."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from sinegor.modules.security_events.service import record_rejection


def error_response(
    request: Request, status: int, code: str, message: str, **kwargs
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message},
            "request_id": getattr(request.state, "request_id", None),
        },
        **kwargs,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        await run_in_threadpool(record_rejection, request, exc.status_code)
        return error_response(
            request,
            exc.status_code,
            f"http_{exc.status_code}",
            str(exc.detail),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        await run_in_threadpool(record_rejection, request, 422, invalid_input=True)
        if request.url.path.startswith("/api/admin/orders/") and request.url.path.endswith(
            "/folder"
        ):
            fields = {tuple(error["loc"]) for error in exc.errors()}
            if ("body", "disk_path") in fields:
                return error_response(request, 422, "disk_invalid_path", "Invalid Disk path")
            if ("body", "name_base") in fields:
                return error_response(request, 422, "disk_invalid_name", "Invalid folder name base")
        return error_response(request, 422, "validation_error", "Request validation failed")
