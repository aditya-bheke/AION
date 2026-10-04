"""Structured JSON logging for the orders service.

Every log record is written as one JSON object per line, which lets the
platform's log collector parse fields (level, request, exception) reliably.
"""
import json
import logging
import os
import traceback
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "service": "orders-service",
            "message": record.getMessage(),
        }
        if hasattr(record, "request"):
            entry["request"] = record.request
        if record.exc_info:
            exc_type, exc, tb = record.exc_info
            entry["exception"] = {
                "type": exc_type.__name__,
                "message": str(exc),
                "stacktrace": "".join(traceback.format_exception(exc_type, exc, tb)),
            }
        return json.dumps(entry)


def configure_logging():
    path = os.getenv("SERVICE_LOG_FILE", "orders-service.log")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("orders")
    logger.setLevel(logging.INFO)
    logger.handlers = [handler]
    logger.propagate = False
