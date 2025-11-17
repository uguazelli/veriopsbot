from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

DEFAULT_LOG_DIR = (
    Path(os.getenv("LOG_DIRECTORY"))
    if os.getenv("LOG_DIRECTORY")
    else Path(__file__).resolve().parents[1] / "logs"
)
DEFAULT_LOG_PATH = Path(
    os.getenv("LOG_FILE_PATH", DEFAULT_LOG_DIR / "veriops.log")
)


class IsoFormatter(logging.Formatter):
    """Format timestamps in ISO-8601 with millisecond precision (UTC)."""

    def formatTime(  # noqa: N802
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(IsoFormatter):
    """Serialize log records as JSON for easier ingestion & UI display."""

    def format(self, record: logging.LogRecord) -> str:
        log_record: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        event = getattr(record, "event", None)
        if event:
            log_record["event"] = event

        payload = getattr(record, "payload", None)
        if payload:
            log_record["payload"] = _safe(payload)

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record, ensure_ascii=False)


_configured = False


def configure_logging() -> None:
    """
    Configure root logging once so every module can emit structured logs.
    - Console handler: human friendly, inherits LOG_LEVEL (INFO default)
    - File handler: JSON lines, rotates via LOG_MAX_BYTES/LOG_BACKUP_COUNT
    """
    global _configured
    if _configured:
        return

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Drop default handlers from uvicorn/fastapi so we own formatting.
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        IsoFormatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
    )
    root_logger.addHandler(console_handler)

    log_to_file = os.getenv("LOG_TO_FILE", "true").lower() not in {"0", "false", "no"}
    if log_to_file:
        log_path = get_log_file_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=int(os.getenv("LOG_MAX_BYTES", 1_000_000)),
            backupCount=int(os.getenv("LOG_BACKUP_COUNT", 5)),
        )
        file_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(file_handler)

    logging.captureWarnings(True)
    _configured = True


def get_log_file_path() -> Path:
    return DEFAULT_LOG_PATH


def _safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)
