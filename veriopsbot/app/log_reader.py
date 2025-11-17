from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .logging_config import get_log_file_path

DEFAULT_LIMIT = 150


def get_recent_logs(
    limit: int = DEFAULT_LIMIT,
    *,
    level: str | None = None,
    event: str | None = None,
    tenant_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> List[Dict[str, Any]]:
    """
    Return the newest log entries (JSON formatted) stored in the log file.
    Optional filters allow slicing by severity, event, tenant/client id, or time range.
    """
    limit = max(1, min(limit, 500))  # guard rails for UI usage
    log_path = Path(get_log_file_path())
    if not log_path.exists():
        return []

    normalized_level = level.lower() if level else None
    normalized_event = event.lower() if event else None
    normalized_tenant = str(tenant_id).strip() if tenant_id else None

    lines: deque[str] = deque(maxlen=limit)
    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if stripped:
                lines.append(stripped)

    entries: List[Dict[str, Any]] = []
    for line in lines:
        entry = _parse_line(line)
        if _matches_filters(
            entry,
            level=normalized_level,
            event=normalized_event,
            tenant_id=normalized_tenant,
            start=start,
            end=end,
        ):
            entries.append(entry)

    # Show newest first
    return list(reversed(entries))


def _parse_line(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw)
        timestamp = data.get("ts") or data.get("timestamp")
        parsed_ts = _parse_timestamp(timestamp)
        return {
            "timestamp": timestamp,
            "timestamp_dt": parsed_ts,
            "level": data.get("level", "INFO"),
            "logger": data.get("logger") or data.get("name") or "app",
            "message": data.get("message", ""),
            "event": data.get("event"),
            "payload": data.get("payload") or {},
        }
    except json.JSONDecodeError:
        return {
            "timestamp": None,
            "timestamp_dt": None,
            "level": "INFO",
            "logger": "raw",
            "message": raw,
            "event": None,
            "payload": {},
        }


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    cooked = value.replace("Z", "+00:00")
    # logging formatter emits +0000 without colon, add it for ISO parsing
    if "+" in cooked[-6:] or "-" in cooked[-6:]:
        if cooked[-3] not in {":", ""} and cooked[-5] in {"+", "-"}:
            cooked = f"{cooked[:-2]}:{cooked[-2:]}"
    try:
        parsed = datetime.fromisoformat(cooked)
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _matches_filters(
    entry: Dict[str, Any],
    *,
    level: str | None,
    event: str | None,
    tenant_id: str | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    if level and entry.get("level", "").lower() != level:
        return False
    event_name = (entry.get("event") or "").lower()
    if event and event_name != event:
        return False
    ts = entry.get("timestamp_dt")
    if start and ts and ts < start:
        return False
    if end and ts and ts > end:
        return False
    if tenant_id and not _payload_contains(entry.get("payload"), tenant_id):
        return False
    return True


def _payload_contains(payload: Any, needle: str) -> bool:
    if payload is None:
        return False
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"tenant_id", "tenant", "account_id", "client_id"}:
                if str(value) == needle:
                    return True
            if _payload_contains(value, needle):
                return True
    elif isinstance(payload, (list, tuple, set)):
        for item in payload:
            if _payload_contains(item, needle):
                return True
    else:
        # Primitive value match fallback
        if str(payload) == needle:
            return True
    return False
