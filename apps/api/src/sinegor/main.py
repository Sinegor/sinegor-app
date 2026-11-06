"""Application factory for uvicorn; importing this module needs no credentials."""

import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from sinegor.api.errors import error_response, register_error_handlers
from sinegor.api.health import router as health_router
from sinegor.core.config import Settings, load_settings
from sinegor.core.logging import configure_logging
from sinegor.db import models  # noqa: F401 -- register ORM relationships at startup
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.integrations.email.smtp import SMTPAuthMailer
from sinegor.integrations.telegram.client import TelegramNotifier
from sinegor.integrations.yandex_disk.client import DiskError, YandexDisk
from sinegor.modules.agreements.router import router as agreements_router
from sinegor.modules.agreements.storage import AgreementStorage
from sinegor.modules.analytics.router import router as analytics_router
from sinegor.modules.auth.router import router as auth_router
from sinegor.modules.auth.security import new_secret, valid_csrf
from sinegor.modules.customers.router import router as customers_router
from sinegor.modules.disk.router import disk_error
from sinegor.modules.disk.router import router as disk_router
from sinegor.modules.notifications.router import router as notifications_router
from sinegor.modules.orders.router import router as orders_router
from sinegor.modules.retention.router import router as retention_router
from sinegor.modules.security_events.permissions import verify_runtime_permissions
from sinegor.modules.security_events.router import router as security_events_router
from sinegor.modules.security_events.service import record_rejection, request_identifier

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_db_engine(settings)
        if settings.app_env == "production":
            try:
                with engine.connect() as connection:
                    verify_runtime_permissions(connection)
            except Exception:
                engine.dispose()
                raise
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        logger.info("application_started")
        try:
            yield
        finally:
            engine.dispose()
            logger.info("application_stopped")

    production = settings.app_env == "production"
    app = FastAPI(
        title="SINEGOR API",
        version="0.1.0",
        lifespan=lifespan,
        debug=False,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.auth_mailer = SMTPAuthMailer(settings)
    app.state.order_mailer = SMTPAuthMailer(settings)
    app.state.notification_mailer = SMTPAuthMailer(settings)
    app.state.telegram_notifier = TelegramNotifier(settings)
    app.state.agreement_storage = AgreementStorage(settings.agreement_storage_dir)
    app.state.csrf_key = (
        settings.session_secret.get_secret_value() if settings.session_secret else new_secret()
    )
    app.state.yandex_disk = YandexDisk(settings)
    app.add_exception_handler(DiskError, disk_error)
    register_error_handlers(app)
    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(customers_router, prefix="/api")
    app.include_router(orders_router, prefix="/api")
    app.include_router(agreements_router, prefix="/api")
    app.include_router(disk_router, prefix="/api")
    app.include_router(notifications_router, prefix="/api")
    app.include_router(retention_router, prefix="/api")
    app.include_router(security_events_router, prefix="/api")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # Generate IDs server-side; never log untrusted IDs, paths, queries or bodies.
        request.state.request_id = uuid4().hex
        context_token = request_identifier.set(request.state.request_id)
        started = perf_counter()
        try:
            if request.url.path.startswith("/api/") and request.method not in {
                "GET",
                "HEAD",
                "OPTIONS",
            }:
                header = request.headers.get("X-CSRF-Token", "")
                cookie = request.cookies.get(settings.csrf_cookie_name, "")
                raw_session = request.cookies.get(settings.session_cookie_name, "")
                origin = str(settings.public_origin).rstrip("/")
                csrf_ok = (
                    request.headers.get("Origin") == origin
                    and len(header) <= 256
                    and len(cookie) <= 256
                    and valid_csrf(
                        header, app.state.csrf_key, raw_session, settings.csrf_ttl_seconds
                    )
                    # Initial requests in different tabs may issue distinct valid tokens.
                    and valid_csrf(
                        cookie, app.state.csrf_key, raw_session, settings.csrf_ttl_seconds
                    )
                )
                if not csrf_ok:
                    await run_in_threadpool(record_rejection, request, 403)
                    response = error_response(request, 403, "csrf_failed", "CSRF validation failed")
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception as exc:
            logger.error(
                "unhandled_error",
                extra={
                    "request_id": request.state.request_id,
                    "exception_type": type(exc).__name__,
                },
            )
            response = error_response(request, 500, "internal_error", "Internal server error")
        request_identifier.reset(context_token)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        logger.info(
            "request_completed",
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return response

    return app
