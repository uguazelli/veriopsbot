"""High-level database operations built on top of raw SQL statements."""

from __future__ import annotations

import os
import json
from datetime import date
from typing import Any, Dict

import anyio
from psycopg.rows import dict_row
from aiocache import Cache

from .connection import get_connection
from . import queries

# --- Cache backend: Memory now, flip to Redis via env without code changes ---
# MEMORY (default): no external service. For production, set CACHE_BACKEND=REDIS.
_BACKEND = os.getenv("CACHE_BACKEND", "MEMORY").upper()
_NAMESPACE = os.getenv("CACHE_NAMESPACE", "veridata")
_DEFAULT_TTL = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # 5 minutes

if _BACKEND == "REDIS":
    _cache = Cache(
        Cache.REDIS,
        endpoint=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        namespace=_NAMESPACE,
    )
else:
    _cache = Cache(Cache.MEMORY, namespace=_NAMESPACE)

async def get_params_by_omnichannel_id(omnichannel_id: int) -> Dict[str, Any]:
    """
    Async, cache-backed accessor.
    - Checks cache first (0 DB hits on cache hit).
    - On miss, runs the original sync query in a thread and caches the result.
    - Switch Memory → Redis by environment variables (no code changes).
    """
    key = f"client_params:{omnichannel_id}"
    cached = await _cache.get(key)
    if cached is not None:
        return cached

    # Original sync query wrapped in a function so we can run it in a worker thread
    def _query() -> Dict[str, Any]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                queries.SQL_GET_PARAMS_BY_OMNICHANNEL_ID,
                {"omnichannel_id": omnichannel_id},
            )
            return cur.fetchone() or {}

    result = await anyio.to_thread.run_sync(_query)

    await _cache.set(key, result, ttl=_DEFAULT_TTL)
    return result


# Call this after you update the DB for that omnichannel_id
async def invalidate_params_cache(omnichannel_id: int) -> None:
    await _cache.delete(f"client_params:{omnichannel_id}")


async def invalidate_tenant_params_cache(tenant_id: int) -> None:
    await _cache.delete(f"tenant_params:{tenant_id}")


async def get_params_by_tenant_id(tenant_id: int) -> Dict[str, Any]:
    """
    Fetch tenant configuration by tenant id (multi-tenant aware ingestion).
    """
    cache_key = f"tenant_params:{tenant_id}"
    cached = await _cache.get(cache_key)
    if cached is not None:
        return cached

    def _query() -> Dict[str, Any]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                queries.SQL_GET_PARAMS_BY_TENANT_ID,
                {"tenant_id": tenant_id},
            )
            return cur.fetchone() or {}

    result = await anyio.to_thread.run_sync(_query)
    await _cache.set(cache_key, result, ttl=_DEFAULT_TTL)
    return result


async def increment_bot_request_count(tenant_id: int, bucket: date | None = None) -> int:
    """
    Increment the bot usage counter for a tenant and return the day's total.
    """
    target_bucket = bucket or date.today()

    def _increment() -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    queries.SQL_INCREMENT_BOT_REQUEST_COUNT,
                    {"tenant_id": tenant_id, "bucket_date": target_bucket},
                )
                new_count = cur.fetchone()[0]
            conn.commit()
            return new_count

    return await anyio.to_thread.run_sync(_increment)


async def get_bot_request_total(tenant_id: int, start: date, end: date | None = None) -> int:
    """
    Return aggregated bot requests for a tenant between start and end dates (inclusive).
    """
    end_date = end or start

    def _fetch() -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    queries.SQL_GET_BOT_REQUEST_COUNT_IN_RANGE,
                    {
                        "tenant_id": tenant_id,
                        "start_date": start,
                        "end_date": end_date,
                    },
                )
                row = cur.fetchone()
                return int(row[0]) if row and row[0] is not None else 0

    return await anyio.to_thread.run_sync(_fetch)


async def get_user_by_email(email: str) -> Dict[str, Any]:
    """
    Fetch a single user record by email. Returns {} when not found.
    """

    def _query() -> Dict[str, Any]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                queries.SQL_GET_USER_BY_EMAIL,
                {"email": email},
            )
            return cur.fetchone() or {}

    return await anyio.to_thread.run_sync(_query)


async def get_user_by_id(user_id: int) -> Dict[str, Any]:
    """
    Fetch a single user record by id. Returns {} when not found.
    """

    def _query() -> Dict[str, Any]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                queries.SQL_GET_USER_BY_ID,
                {"user_id": user_id},
            )
            return cur.fetchone() or {}

    return await anyio.to_thread.run_sync(_query)


async def create_user(
    tenant_id: int,
    email: str,
    password_hash: str,
    *,
    is_admin: bool = False,
) -> Dict[str, Any]:
    """
    Insert a new user row and return the created record.
    """

    def _insert() -> Dict[str, Any]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                queries.SQL_INSERT_USER,
                {
                    "tenant_id": tenant_id,
                    "email": email,
                    "password_hash": password_hash,
                    "is_admin": is_admin,
                },
            )
            row = cur.fetchone() or {}
            conn.commit()
            return row

    return await anyio.to_thread.run_sync(_insert)


async def update_user_account(
    user_id: int,
    *,
    email: str,
    password_hash: str | None = None,
) -> Dict[str, Any]:
    """
    Update a user's email and/or password hash.
    """

    def _update() -> Dict[str, Any]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                queries.SQL_UPDATE_USER_ACCOUNT,
                {
                    "user_id": user_id,
                    "email": email,
                    "password_hash": password_hash,
                },
            )
            row = cur.fetchone() or {}
            conn.commit()
            return row

    return await anyio.to_thread.run_sync(_update)


async def update_llm_settings(
    llm_id: int,
    params: Dict[str, Any],
) -> None:
    """
    Persist new LLM settings for a tenant.
    """

    def _update() -> None:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                queries.SQL_UPDATE_LLM_SETTINGS,
                {
                    "llm_id": llm_id,
                    "params": json.dumps(params),
                },
            )
            conn.commit()

    await anyio.to_thread.run_sync(_update)


async def update_crm_settings(
    crm_id: int,
    params: Dict[str, Any],
) -> None:
    """
    Persist new CRM settings for a tenant.
    """

    def _update() -> None:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                queries.SQL_UPDATE_CRM_SETTINGS,
                {
                    "crm_id": crm_id,
                    "params": json.dumps(params),
                },
            )
            conn.commit()

    await anyio.to_thread.run_sync(_update)


async def update_omnichannel_settings(
    omnichannel_id: int,
    params: Dict[str, Any],
) -> None:
    """
    Persist new omnichannel (Chatwoot) settings for a tenant.
    """

    def _update() -> None:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                queries.SQL_UPDATE_OMNICHANNEL_SETTINGS,
                {
                    "omnichannel_id": omnichannel_id,
                    "params": json.dumps(params),
                },
            )
            conn.commit()

    await anyio.to_thread.run_sync(_update)


async def list_tenants() -> list[Dict[str, Any]]:
    """
    List all tenants.
    """
    def _query() -> list[Dict[str, Any]]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(queries.SQL_LIST_TENANTS)
            return cur.fetchall()

    return await anyio.to_thread.run_sync(_query)


async def upsert_llm_settings(
    tenant_id: int,
    params: Dict[str, Any],
    llm_id: int | None = None,
) -> None:
    """
    Update LLM settings if llm_id exists, otherwise insert.
    """
    def _action() -> None:
        with get_connection() as conn, conn.cursor() as cur:
            if llm_id:
                cur.execute(
                    queries.SQL_UPDATE_LLM_SETTINGS,
                    {
                        "llm_id": llm_id,
                        "params": json.dumps(params),
                    },
                )
            else:
                cur.execute(
                    queries.SQL_INSERT_LLM_SETTINGS,
                    {
                        "tenant_id": tenant_id,
                        "params": json.dumps(params),
                    },
                )
            conn.commit()

    await anyio.to_thread.run_sync(_action)


async def upsert_crm_settings(
    tenant_id: int,
    params: Dict[str, Any],
    crm_id: int | None = None,
) -> None:
    """
    Update CRM settings if crm_id exists, otherwise insert.
    """
    def _action() -> None:
        with get_connection() as conn, conn.cursor() as cur:
            if crm_id:
                cur.execute(
                    queries.SQL_UPDATE_CRM_SETTINGS,
                    {
                        "crm_id": crm_id,
                        "params": json.dumps(params),
                    },
                )
            else:
                cur.execute(
                    queries.SQL_INSERT_CRM_SETTINGS,
                    {
                        "tenant_id": tenant_id,
                        "params": json.dumps(params),
                    },
                )
            conn.commit()

    await anyio.to_thread.run_sync(_action)


async def upsert_omnichannel_settings(
    tenant_id: int,
    params: Dict[str, Any],
    omnichannel_id: int | None = None,
) -> None:
    """
    Update Omnichannel settings if omnichannel_id exists, otherwise insert.
    """
    def _action() -> None:
        with get_connection() as conn, conn.cursor() as cur:
            if omnichannel_id:
                cur.execute(
                    queries.SQL_UPDATE_OMNICHANNEL_SETTINGS,
                    {
                        "omnichannel_id": omnichannel_id,
                        "params": json.dumps(params),
                    },
                )
            else:
                cur.execute(
                    queries.SQL_INSERT_OMNICHANNEL_SETTINGS,
                    {
                        "tenant_id": tenant_id,
                        "params": json.dumps(params),
                    },
                )
            conn.commit()

    await anyio.to_thread.run_sync(_action)
