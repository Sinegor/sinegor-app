"""Structured logs containing only explicitly allowed service metadata."""

import json
import logging
from datetime import UTC, datetime
from logging.config import dictConfig

SAFE_FIELDS = ("request_id", "method", "status_code", "duration_ms", "exception_type")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for name in SAFE_FIELDS:
            if hasattr(record, name):
                data[name] = getattr(record, name)
        # Exception text/traceback can contain SQL parameters, URLs and tokens.
        return json.dumps(data, ensure_ascii=False)


def configure_logging(level: str) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json",
                }
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                # Do not emit request URLs (Magic Link) or SQL parameters.
                "uvicorn.access": {"handlers": [], "propagate": False},
                "sqlalchemy.engine": {"handlers": [], "propagate": False, "level": "CRITICAL"},
                "httpx": {"handlers": [], "propagate": False, "level": "WARNING"},
                "httpx2": {"handlers": [], "propagate": False, "level": "WARNING"},
                "httpcore": {"handlers": [], "propagate": False, "level": "WARNING"},
            },
        }
    )
