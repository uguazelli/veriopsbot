from __future__ import annotations

import json
import logging
import mimetypes
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlencode

import anyio
import bcrypt
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.controller import rag_docs, rag_ingest
from app.log_reader import get_recent_logs
from app.db.repository import (
    create_user,
    get_params_by_tenant_id,
    get_user_by_email,
    get_user_by_id,
    invalidate_params_cache,
    invalidate_tenant_params_cache,
    update_crm_settings,
    update_llm_settings,
    update_omnichannel_settings,
    update_user_account,
)

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

logger = logging.getLogger("veriops.web")

SESSION_COOKIE_NAME = "session_token"
SESSION_MAX_AGE = 60 * 60 * 8  # 8 hours
SESSION_STORE: dict[str, Dict[str, Any]] = {}

PROVIDER_OPTIONS: list[str] = [
    "openai",
    # "gemini"
    ]
MODEL_OPTIONS: list[str] = [
    "gpt-4o-mini",
    # "gpt-4o",
    # "gpt-4.1-mini",
    # "gpt-3.5-turbo",
    # "claude-3-haiku",
]
HANDOFF_PRIORITIES: list[str] = ["low", "medium", "high", "urgent"]
EMBED_MODEL_OPTIONS: list[str] = [
    "text-embedding-3-small",
    # "text-embedding-3-large",
    # "text-embedding-ada-002",
    # "models/text-embedding-004",
]
CROSS_ENCODER_OPTIONS: list[str] = [
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    # "cross-encoder/ms-marco-electra-base",
    # "cross-encoder/stsb-roberta-base",
]
LOG_LEVEL_OPTIONS: list[str] = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
DEFAULT_LOG_LIMIT = 200

# =========================
# 🔎 Debug helpers (safe)
# =========================
REDACT_KEYS = {
    "password", "confirm_password",
    "llm_api_key", "crm_token",
    "chatwoot_api_access_token", "chatwoot_bot_access_token",
    "token", "api_key", "authorization", "auth", "bearer", "secret", "password_hash",
}

def _safe_value(key: str, value: Any) -> Any:
    try:
        k = key.lower()
    except Exception:
        k = key
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if any(s in k for s in REDACT_KEYS):
        return "******"
    # avoid dumping massive strings
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value

def _safe_map(d: Dict[str, Any] | None) -> Dict[str, Any]:
    if not d:
        return {}
    return {k: _safe_value(k, v) for k, v in d.items()}

def _log(event: str, **fields: Any) -> None:
    # event emoji map
    prefix = {
        "enter": "🟢",
        "exit": "🔵",
        "warn": "🟠",
        "error": "❌",
        "info": "🧭",
        "db": "🗄️",
        "session": "🧩",
        "files": "📂",
        "form": "📮",
        "ingest": "🧪",
    }.get(event, "🔹")
    payload = {k: _safe_value(k, v) for k, v in fields.items()}
    message = f"{prefix} {event.upper()} {json.dumps(payload, ensure_ascii=False)}"
    level = {
        "error": logging.ERROR,
        "warn": logging.WARNING,
        "db": logging.INFO,
        "enter": logging.DEBUG,
        "exit": logging.DEBUG,
    }.get(event, logging.INFO)
    logger.log(level, message, extra={"event": event, "payload": payload})


def _parse_datetime_param(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _clamp_log_limit(raw_value: str | None) -> int:
    try:
        value = int(raw_value) if raw_value is not None else DEFAULT_LOG_LIMIT
    except (TypeError, ValueError):
        value = DEFAULT_LOG_LIMIT
    return max(25, min(value, 500))


# =========================
# Internal helpers (unchanged, with logs)
# =========================

def _redirect_documents(**params: str | None) -> RedirectResponse:
    final_params = {key: value for key, value in params.items() if value}
    query = urlencode(final_params)
    base_url = "/settings"
    if query:
        base_url = f"{base_url}?{query}"
    url = f"{base_url}#documents"
    _log("info", action="redirect_documents", url=url, params=final_params)
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _get_session(request: Request) -> Dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    has_token = bool(token)
    session = SESSION_STORE.get(token) if token else None
    _log("session", action="_get_session", has_token=has_token, session_found=bool(session))
    return session


def _issue_session_response(
    user: Dict[str, Any],
    *,
    redirect_url: str = "/settings",
) -> RedirectResponse:
    token = secrets.token_urlsafe(32)
    SESSION_STORE[token] = {
        "user_id": user["id"],
        "tenant_id": user["tenant_id"],
        "email": user["email"],
        "is_admin": bool(user.get("is_admin")),
    }
    response = RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    _log("session", action="_issue_session_response", redirect_url=redirect_url, user_id=user.get("id"), tenant_id=user.get("tenant_id"))
    return response


def _client_folder_name(session: Dict[str, Any]) -> str:
    name = rag_docs.tenant_folder_name(
        tenant_id=session["tenant_id"],
        tenant_email=session.get("email"),
    )
    _log("files", action="_client_folder_name", folder=name, tenant_id=session.get("tenant_id"))
    return name


def _file_type_label(file_name: str) -> str:
    mime, _ = mimetypes.guess_type(file_name)
    if mime:
        _, _, subtype = mime.partition("/")
        if subtype:
            return subtype.replace("-", " ").upper()
        return mime.upper()
    suffix = Path(file_name).suffix.lstrip(".")
    if suffix:
        return suffix.upper()
    return "Unknown"


def _build_file_rows(folder_name: str, file_names: list[str]) -> list[Dict[str, str]]:
    rows: list[Dict[str, str]] = []
    for file_name in file_names:
        rows.append(
            {
                "name": file_name,
                "type": _file_type_label(file_name),
                "url": f"/rag/docs/{folder_name}/{file_name}",
            }
        )
    _log("files", action="_build_file_rows", folder=folder_name, count=len(rows))
    return rows


def _build_documents_context(session: Dict[str, Any]) -> Dict[str, Any]:
    folder_name = _client_folder_name(session)
    rag_docs.ensure_folder(folder_name)
    try:
        client_files = rag_docs.list_folder_files(folder_name)
        _log("files", action="list_folder_files", folder=folder_name, count=len(client_files))
    except FileNotFoundError:
        _log("warn", action="list_folder_files", folder=folder_name, reason="FileNotFoundError")
        client_files = []
    file_rows = _build_file_rows(folder_name, client_files)
    return {
        "client_folder": folder_name,
        "file_rows": file_rows,
    }


def _settings_template_context(
    request: Request,
    session: Dict[str, Any],
    form_values: Dict[str, str],
    *,
    message: str | None,
    errors: list[str],
    documents_message: str | None = None,
    account_form: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "request": request,
        "user_email": session["email"],
        "is_admin": session.get("is_admin", False),
        "form_values": form_values,
        "message": message,
        "errors": errors,
        "documents_message": documents_message,
        "account_form": account_form or {"new_email": ""},
        "provider_options": PROVIDER_OPTIONS,
        "model_options": MODEL_OPTIONS,
        "handoff_priorities": HANDOFF_PRIORITIES,
        "embed_options": EMBED_MODEL_OPTIONS,
        "cross_encoder_options": CROSS_ENCODER_OPTIONS,
    }
    context.update(_build_documents_context(session))
    return context


def _admin_template_context(
    request: Request,
    session: Dict[str, Any],
    *,
    message: str | None = None,
    errors: list[str] | None = None,
    form_data: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    return {
        "request": request,
        "user_email": session["email"],
        "is_admin": True,
        "message": message,
        "errors": errors or [],
        "form_data": form_data or {"target_email": "", "new_email": ""},
    }


def _build_form_values(
    config: Dict[str, Any],
    overrides: Dict[str, str] | None = None,
) -> Dict[str, str]:
    overrides = overrides or {}
    llm_params = config.get("llm_params") or {}
    crm_params = config.get("crm_params") or {}
    omni_params = config.get("omnichannel") or {}

    def pick(key: str, default: Any = "") -> str:
        if overrides is not None and key in overrides:
            value = overrides[key]
        else:
            value = default
        return "" if value is None else str(value)

    values = {
        "llm_name": pick("llm_name", llm_params.get("name")),
        "llm_api_key": pick("llm_api_key", llm_params.get("api_key")),
        "llm_model_answer": pick("llm_model_answer", llm_params.get("model_answer")),
        "llm_top_k": pick("llm_top_k", llm_params.get("top_k")),
        "llm_temperature": pick("llm_temperature", llm_params.get("temperature")),
        "llm_handoff_priority": pick(
            "llm_handoff_priority",
            llm_params.get("handoff_priority"),
        ),
        "llm_openai_embed_model": pick(
            "llm_openai_embed_model",
            llm_params.get("openai_embed_model"),
        ),
        "llm_handoff_private_note": pick(
            "llm_handoff_private_note",
            llm_params.get("handoff_private_note"),
        ),
        "llm_handoff_public_reply": pick(
            "llm_handoff_public_reply",
            llm_params.get("handoff_public_reply"),
        ),
        "llm_rag_cross_encoder_model": pick(
            "llm_rag_cross_encoder_model",
            llm_params.get("rag_cross_encoder_model"),
        ),
        "llm_monthly_limit": pick(
            "llm_monthly_limit",
            llm_params.get("monthly_llm_request_limit"),
        ),
        "crm_url": pick("crm_url", crm_params.get("url")),
        "crm_token": pick("crm_token", crm_params.get("token")),
        "chatwoot_api_url": pick(
            "chatwoot_api_url",
            omni_params.get("chatwoot_api_url"),
        ),
        "chatwoot_account_id": pick(
            "chatwoot_account_id",
            omni_params.get("chatwoot_account_id"),
        ),
        "chatwoot_api_access_token": pick(
            "chatwoot_api_access_token",
            omni_params.get("chatwoot_api_access_token"),
        ),
        "chatwoot_bot_access_token": pick(
            "chatwoot_bot_access_token",
            omni_params.get("chatwoot_bot_access_token"),
        ),
    }
    _log("form", action="_build_form_values", overrides_present=bool(overrides), keys=list(values.keys()))
    return values


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    _log("enter", route="GET /")
    session = _get_session(request)
    target = "/settings" if session else "/login"
    _log("exit", route="GET /", redirect=target)
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    _log("enter", route="GET /login")
    session = _get_session(request)
    if session:
        _log("info", route="GET /login", detail="already logged in, redirecting /settings")
        return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)

    _log("exit", route="GET /login", template="login.html")
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "email": "",
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request):
    _log("enter", route="POST /login")
    form = await request.form()
    _log("form", route="POST /login", received=_safe_map(dict(form)))
    email_raw = (form.get("email") or "").strip()
    password = form.get("password") or ""
    email = email_raw.lower()

    if not email or not password:
        _log("warn", route="POST /login", reason="missing email or password")
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Email and password are required.",
                "email": email_raw,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = await get_user_by_email(email)
        _log("db", op="get_user_by_email", email=email, user_found=bool(user))
    except Exception as e:
        _log("error", route="POST /login", during="get_user_by_email", error=str(e))
        raise

    password_hash = user.get("password_hash") if user else None

    if not user or not password_hash:
        _log("warn", route="POST /login", reason="user not found or no password hash")
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid email or password.",
                "email": email_raw,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
        _log("warn", route="POST /login", reason="password mismatch", email=email)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid email or password.",
                "email": email_raw,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    _log("exit", route="POST /login", status="success")
    return _issue_session_response(user)


@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    _log("enter", route="GET /register")
    session = _get_session(request)
    if session:
        _log("info", route="GET /register", detail="already logged in, redirecting /settings")
        return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)

    _log("exit", route="GET /register", template="register.html")
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "errors": [],
            "email": "",
            "tenant_id": "",
        },
    )


@router.post("/register", response_class=HTMLResponse)
async def register(request: Request):
    _log("enter", route="POST /register")
    session = _get_session(request)
    if session:
        _log("info", route="POST /register", detail="already logged in, redirecting /settings")
        return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    _log("form", route="POST /register", received=_safe_map(dict(form)))
    email_raw = (form.get("email") or "").strip()
    email = email_raw.lower()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""
    tenant_id_raw = (form.get("tenant_id") or "").strip()

    errors: list[str] = []
    tenant_id: int | None = None

    if not tenant_id_raw:
        errors.append("Tenant ID is required.")
    else:
        try:
            tenant_id = int(tenant_id_raw)
        except ValueError:
            errors.append("Tenant ID must be a number.")

    if not email:
        errors.append("Email is required.")
    if not password:
        errors.append("Password is required.")
    if password and len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if password != confirm_password:
        errors.append("Passwords do not match.")

    try:
        existing_user = await get_user_by_email(email) if email else {}
        _log("db", op="get_user_by_email", email=email, exists=bool(existing_user))
    except Exception as e:
        _log("error", route="POST /register", during="get_user_by_email", error=str(e))
        raise

    if existing_user:
        errors.append("An account with this email already exists.")

    if errors:
        _log("warn", route="POST /register", errors=errors)
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "errors": errors,
                "email": email_raw,
                "tenant_id": tenant_id_raw,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )

    try:
        assert tenant_id is not None
        user = await create_user(
            tenant_id=tenant_id,
            email=email,
            password_hash=password_hash,
        )
        _log("db", op="create_user", tenant_id=tenant_id, email=email, success=True)
    except Exception as e:
        _log("error", route="POST /register", during="create_user", error=str(e))
        errors.append("Failed to create user. Please try again or contact support.")
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "errors": errors,
                "email": email_raw,
                "tenant_id": tenant_id_raw,
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    _log("exit", route="POST /register", status="success")
    return _issue_session_response(user)


@router.get("/logout")
async def logout(request: Request):
    _log("enter", route="GET /logout")
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        SESSION_STORE.pop(token, None)
        _log("session", action="logout", removed_token=bool(token))
    response = RedirectResponse(
        url="/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(SESSION_COOKIE_NAME)
    _log("exit", route="GET /logout", redirect="/login")
    return response


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    _log("enter", route="GET /settings")
    session = _get_session(request)
    if not session:
        _log("warn", route="GET /settings", reason="no session -> redirect /login")
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        config = await get_params_by_tenant_id(session["tenant_id"])
        _log("db", op="get_params_by_tenant_id", tenant_id=session["tenant_id"], has_config=bool(config))
    except Exception as e:
        _log("error", route="GET /settings", during="get_params_by_tenant_id", error=str(e))
        raise

    form_values = _build_form_values(config)
    message = request.query_params.get("message")
    errors: list[str] = []
    error_param = request.query_params.get("error")
    if error_param:
        errors.append(error_param)
    _log("exit", route="GET /settings", template="settings.html")
    return templates.TemplateResponse(
        "settings.html",
        _settings_template_context(
            request,
            session,
            form_values,
            message=message,
            errors=errors,
            documents_message=message,
        ),
    )


@router.post("/settings", response_class=HTMLResponse)
async def update_settings(request: Request):
    _log("enter", route="POST /settings")
    session = _get_session(request)
    if not session:
        _log("warn", route="POST /settings", reason="no session -> redirect /login")
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        config = await get_params_by_tenant_id(session["tenant_id"])
        _log("db", op="get_params_by_tenant_id", tenant_id=session["tenant_id"], has_config=bool(config))
    except Exception as e:
        _log("error", route="POST /settings", during="get_params_by_tenant_id", error=str(e))
        raise

    form = await request.form()
    form_dict: Dict[str, str] = {
        key: (value.strip() if isinstance(value, str) else value)
        for key, value in form.items()
    }
    _log("form", route="POST /settings", received=_safe_map(form_dict))

    form_values = _build_form_values(config, overrides=form_dict)
    errors: list[str] = []

    if not config:
        errors.append("Tenant configuration not found. Please contact support.")

    current_llm = config.get("llm_params") or {}
    current_crm = config.get("crm_params") or {}
    current_omni = config.get("omnichannel") or {}

    required_fields = {
        "llm_name": "LLM name",
        "llm_api_key": "LLM API key",
        "llm_model_answer": "LLM model answer",
        "crm_url": "CRM URL",
        "crm_token": "CRM token",
        "chatwoot_api_url": "Chatwoot API URL",
        "chatwoot_account_id": "Chatwoot account ID",
        "chatwoot_api_access_token": "Chatwoot API access token",
        "chatwoot_bot_access_token": "Chatwoot bot access token",
    }
    existing_required_values = {
        "llm_name": current_llm.get("name"),
        "llm_api_key": current_llm.get("api_key"),
        "llm_model_answer": current_llm.get("model_answer"),
        "crm_url": current_crm.get("url"),
        "crm_token": current_crm.get("token"),
        "chatwoot_api_url": current_omni.get("chatwoot_api_url"),
        "chatwoot_account_id": current_omni.get("chatwoot_account_id"),
        "chatwoot_api_access_token": current_omni.get("chatwoot_api_access_token"),
        "chatwoot_bot_access_token": current_omni.get("chatwoot_bot_access_token"),
    }
    effective_inputs: Dict[str, str] = {}
    for field, label in required_fields.items():
        submitted_value = form_dict.get(field)
        if submitted_value is not None:
            candidate = submitted_value
        else:
            candidate = None
        if isinstance(candidate, str) and candidate == "":
            candidate = None
        if candidate is None:
            candidate = existing_required_values.get(field)
        if not candidate:
            errors.append(f"{label} is required.")
        else:
            effective_inputs[field] = str(candidate)

    top_k_raw = form_dict.get("llm_top_k", "")
    top_k = current_llm.get("top_k")
    if top_k_raw:
        try:
            top_k = int(top_k_raw)
        except ValueError:
            errors.append("LLM Top K must be an integer.")

    temperature_raw = form_dict.get("llm_temperature", "")
    temperature = current_llm.get("temperature")
    if temperature_raw:
        try:
            temperature = float(temperature_raw)
        except ValueError:
            errors.append("LLM temperature must be a number.")

    monthly_limit_raw = form_dict.get("llm_monthly_limit", "")
    monthly_limit = current_llm.get("monthly_llm_request_limit")
    if monthly_limit_raw == "":
        monthly_limit = None
    elif monthly_limit_raw:
        try:
            monthly_limit = int(monthly_limit_raw)
        except ValueError:
            errors.append("Monthly LLM request limit must be an integer.")

    llm_id = config.get("llm_id")
    crm_id = config.get("crm_id")
    omnichannel_id = config.get("omnichannel_id")
    if not llm_id:
        errors.append("LLM settings are missing for this tenant.")
    if not crm_id:
        errors.append("CRM settings are missing for this tenant.")
    if not omnichannel_id:
        errors.append("Omnichannel settings are missing for this tenant.")

    if errors:
        _log("warn", route="POST /settings", errors=errors)
        return templates.TemplateResponse(
            "settings.html",
            _settings_template_context(
                request,
                session,
                form_values,
                message=None,
                errors=errors,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    updated_llm_params = dict(current_llm)
    updated_llm_params["name"] = effective_inputs["llm_name"]
    updated_llm_params["api_key"] = effective_inputs["llm_api_key"]
    updated_llm_params["model_answer"] = effective_inputs["llm_model_answer"]

    def set_or_pop(mapping: Dict[str, Any], key: str, value: Any) -> None:
        if value is None:
            mapping.pop(key, None)
        elif isinstance(value, str) and value == "":
            mapping.pop(key, None)
        else:
            mapping[key] = value

    set_or_pop(
        updated_llm_params,
        "handoff_priority",
        form_dict.get("llm_handoff_priority"),
    )
    set_or_pop(
        updated_llm_params,
        "openai_embed_model",
        form_dict.get("llm_openai_embed_model"),
    )
    set_or_pop(
        updated_llm_params,
        "handoff_private_note",
        form_dict.get("llm_handoff_private_note"),
    )
    set_or_pop(
        updated_llm_params,
        "handoff_public_reply",
        form_dict.get("llm_handoff_public_reply"),
    )
    set_or_pop(
        updated_llm_params,
        "rag_cross_encoder_model",
        form_dict.get("llm_rag_cross_encoder_model"),
    )

    if top_k is None:
        updated_llm_params.pop("top_k", None)
    else:
        updated_llm_params["top_k"] = top_k

    if temperature is None:
        updated_llm_params.pop("temperature", None)
    else:
        updated_llm_params["temperature"] = temperature

    if monthly_limit is None:
        updated_llm_params.pop("monthly_llm_request_limit", None)
    else:
        updated_llm_params["monthly_llm_request_limit"] = monthly_limit

    updated_crm_params = dict(current_crm)
    updated_crm_params["url"] = effective_inputs["crm_url"]
    updated_crm_params["token"] = effective_inputs["crm_token"]

    updated_omni_params = dict(current_omni)
    updated_omni_params["chatwoot_api_url"] = effective_inputs["chatwoot_api_url"]
    updated_omni_params["chatwoot_account_id"] = effective_inputs["chatwoot_account_id"]
    updated_omni_params["chatwoot_api_access_token"] = effective_inputs[
        "chatwoot_api_access_token"
    ]
    updated_omni_params["chatwoot_bot_access_token"] = effective_inputs[
        "chatwoot_bot_access_token"
    ]

    try:
        await update_llm_settings(
            llm_id=llm_id,
            params=updated_llm_params,
        )
        _log("db", op="update_llm_settings", llm_id=llm_id, ok=True)

        await update_crm_settings(
            crm_id=crm_id,
            params=updated_crm_params,
        )
        _log("db", op="update_crm_settings", crm_id=crm_id, ok=True)

        await update_omnichannel_settings(
            omnichannel_id=omnichannel_id,
            params=updated_omni_params,
        )
        _log("db", op="update_omnichannel_settings", omnichannel_id=omnichannel_id, ok=True)

        await invalidate_params_cache(omnichannel_id)
        await invalidate_tenant_params_cache(session["tenant_id"])
        _log("db", op="invalidate_caches", omnichannel_id=omnichannel_id, tenant_id=session["tenant_id"], ok=True)
    except Exception as e:
        _log("error", route="POST /settings", during="update_settings_and_invalidate", error=str(e))
        raise

    refreshed_config = await get_params_by_tenant_id(session["tenant_id"])
    refreshed_form_values = _build_form_values(refreshed_config)

    _log("exit", route="POST /settings", status="success")
    return templates.TemplateResponse(
        "settings.html",
        _settings_template_context(
            request,
            session,
            refreshed_form_values,
            message="Settings updated successfully.",
            errors=[],
        ),
    )


def _ensure_admin_session(request: Request) -> Dict[str, Any] | None:
    session = _get_session(request)
    if not session or not session.get("is_admin"):
        return None
    return session


@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs_page(request: Request):
    session = _ensure_admin_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    params = request.query_params
    client_id = (params.get("client_id") or "").strip()
    level_raw = (params.get("level") or "").upper()
    level = level_raw if level_raw in LOG_LEVEL_OPTIONS else ""
    event = (params.get("event") or "").strip()
    start_input = params.get("start") or ""
    end_input = params.get("end") or ""
    start_dt = _parse_datetime_param(start_input)
    end_dt = _parse_datetime_param(end_input)
    limit = _clamp_log_limit(params.get("limit"))

    def _load_logs() -> list[Dict[str, Any]]:
        return get_recent_logs(
            limit=limit,
            level=level or None,
            event=event or None,
            tenant_id=client_id or None,
            start=start_dt,
            end=end_dt,
        )

    try:
        logs = await anyio.to_thread.run_sync(_load_logs)
    except Exception as exc:
        _log("error", route="GET /admin/logs", during="load_logs", error=str(exc))
        logs = []

    return templates.TemplateResponse(
        "admin_logs.html",
        {
            "request": request,
            "user_email": session["email"],
            "is_admin": True,
            "logs": logs,
            "logs_count": len(logs),
            "filters": {
                "client_id": client_id,
                "level": level,
                "event": event,
                "start": start_input,
                "end": end_input,
                "limit": limit,
            },
            "level_options": LOG_LEVEL_OPTIONS,
        },
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    session = _ensure_admin_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    message = request.query_params.get("message")
    return templates.TemplateResponse(
        "admin_users.html",
        _admin_template_context(
            request,
            session,
            message=message,
            errors=[],
        ),
    )


@router.post("/admin/users", response_class=HTMLResponse)
async def admin_update_user(request: Request):
    session = _ensure_admin_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    form_dict: Dict[str, str] = {
        key: (value.strip() if isinstance(value, str) else value)
        for key, value in form.items()
    }
    _log("form", route="POST /admin/users", received=_safe_map(form_dict))

    target_email_raw = (form_dict.get("target_email") or "").strip()
    target_email = target_email_raw.lower()
    new_email_raw = (form_dict.get("new_email") or "").strip()
    new_email = new_email_raw.lower()
    new_password = form_dict.get("new_password") or ""
    confirm_new_password = form_dict.get("confirm_new_password") or ""

    form_data = {
        "target_email": target_email_raw,
        "new_email": new_email_raw,
    }

    errors: list[str] = []

    if not target_email:
        errors.append("Client email is required.")

    target_user: Dict[str, Any] = {}
    if not errors:
        try:
            target_user = await get_user_by_email(target_email)
            _log("db", op="get_user_by_email", email=target_email, found=bool(target_user))
        except Exception as e:
            _log("error", route="POST /admin/users", during="get_user_by_email", error=str(e))
            raise
        if not target_user:
            errors.append("Client account was not found.")

    if not new_email and not new_password:
        errors.append("Enter a new email or password to update the client account.")

    if new_email:
        if "@" not in new_email or "." not in new_email:
            errors.append("Enter a valid new email address.")
        elif target_user and new_email == target_user.get("email"):
            errors.append("New email must differ from the current email.")
        else:
            try:
                existing = await get_user_by_email(new_email)
                _log("db", op="get_user_by_email", email=new_email, exists=bool(existing))
            except Exception as e:
                _log("error", route="POST /admin/users", during="get_user_by_email(new)", error=str(e))
                raise
            if existing and target_user and existing.get("id") != target_user.get("id"):
                errors.append("That email is already assigned to another user.")

    password_hash_update: str | None = None
    if new_password:
        if len(new_password) < 8:
            errors.append("New password must be at least 8 characters long.")
        if new_password != confirm_new_password:
            errors.append("New password and confirmation do not match.")
        if not errors:
            password_hash_update = bcrypt.hashpw(
                new_password.encode("utf-8"),
                bcrypt.gensalt(),
            ).decode("utf-8")

    if errors:
        _log("warn", route="POST /admin/users", errors=errors)
        return templates.TemplateResponse(
            "admin_users.html",
            _admin_template_context(
                request,
                session,
                errors=errors,
                form_data=form_data,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    updated_email = new_email if new_email else target_user["email"]

    try:
        updated_user = await update_user_account(
            user_id=target_user["id"],
            email=updated_email,
            password_hash=password_hash_update,
        )
        _log("db", op="update_user_account", target_id=target_user["id"], success=bool(updated_user))
    except Exception as e:
        _log("error", route="POST /admin/users", during="update_user_account", error=str(e))
        errors.append("Unable to update the client account. Please try again.")
        return templates.TemplateResponse(
            "admin_users.html",
            _admin_template_context(
                request,
                session,
                errors=errors,
                form_data=form_data,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if target_user["id"] == session["user_id"]:
        session["email"] = updated_user.get("email", updated_email)

    message = f"Updated credentials for {updated_user.get('email', updated_email)}."
    _log("exit", route="POST /admin/users", status="success")
    return templates.TemplateResponse(
        "admin_users.html",
        _admin_template_context(
            request,
            session,
            message=message,
            form_data={"target_email": "", "new_email": ""},
        ),
    )


@router.post("/settings/account", response_class=HTMLResponse)
async def update_account_settings(request: Request):
    _log("enter", route="POST /settings/account")
    session = _get_session(request)
    if not session:
        _log("warn", route="POST /settings/account", reason="no session -> redirect /login")
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        config = await get_params_by_tenant_id(session["tenant_id"])
        _log("db", op="get_params_by_tenant_id", tenant_id=session["tenant_id"], has_config=bool(config))
    except Exception as e:
        _log("error", route="POST /settings/account", during="get_params_by_tenant_id", error=str(e))
        raise

    form = await request.form()
    form_dict: Dict[str, str] = {
        key: (value.strip() if isinstance(value, str) else value)
        for key, value in form.items()
    }
    _log("form", route="POST /settings/account", received=_safe_map(form_dict))

    new_email_raw = (form_dict.get("new_email") or "").strip()
    new_email = new_email_raw.lower()
    current_password = form_dict.get("current_password") or ""
    new_password = form_dict.get("new_password") or ""
    confirm_new_password = form_dict.get("confirm_new_password") or ""

    errors: list[str] = []

    try:
        user = await get_user_by_id(session["user_id"])
        _log("db", op="get_user_by_id", user_id=session["user_id"], found=bool(user))
    except Exception as e:
        _log("error", route="POST /settings/account", during="get_user_by_id", error=str(e))
        raise

    if not user:
        errors.append("User account not found. Please log in again.")

    if not current_password:
        errors.append("Current password is required.")

    changes_requested = bool(new_email) or bool(new_password)
    if not changes_requested:
        errors.append("Provide a new email or password to update your account.")

    password_hash = (user or {}).get("password_hash")
    if not errors:
        if not password_hash or not bcrypt.checkpw(
            current_password.encode("utf-8"),
            password_hash.encode("utf-8"),
        ):
            errors.append("Current password is incorrect.")

    if new_email:
        if "@" not in new_email or "." not in new_email:
            errors.append("Enter a valid email address.")
        elif user and new_email == user.get("email"):
            errors.append("New email must be different from the current email.")
        else:
            try:
                existing = await get_user_by_email(new_email)
                _log("db", op="get_user_by_email", email=new_email, exists=bool(existing))
            except Exception as e:
                _log("error", route="POST /settings/account", during="get_user_by_email", error=str(e))
                raise
            if existing and existing.get("id") != (user or {}).get("id"):
                errors.append("That email is already in use.")

    password_hash_update: str | None = None
    if new_password:
        if len(new_password) < 8:
            errors.append("New password must be at least 8 characters long.")
        if new_password != confirm_new_password:
            errors.append("New password and confirmation do not match.")
        if not errors:
            password_hash_update = bcrypt.hashpw(
                new_password.encode("utf-8"),
                bcrypt.gensalt(),
            ).decode("utf-8")

    form_values = _build_form_values(config)

    if errors:
        _log("warn", route="POST /settings/account", errors=errors)
        return templates.TemplateResponse(
            "settings.html",
            _settings_template_context(
                request,
                session,
                form_values,
                message=None,
                errors=errors,
                account_form={"new_email": new_email_raw},
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    updated_email = new_email if new_email else user["email"]

    try:
        updated_user = await update_user_account(
            user_id=user["id"],
            email=updated_email,
            password_hash=password_hash_update,
        )
        _log("db", op="update_user_account", user_id=user["id"], success=bool(updated_user))
    except Exception as e:
        _log("error", route="POST /settings/account", during="update_user_account", error=str(e))
        errors.append("Unable to update account. Please try again.")
        return templates.TemplateResponse(
            "settings.html",
            _settings_template_context(
                request,
                session,
                form_values,
                message=None,
                errors=errors,
                account_form={"new_email": new_email_raw},
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    session["email"] = updated_user.get("email", updated_email)

    _log("exit", route="POST /settings/account", status="success")
    return templates.TemplateResponse(
        "settings.html",
        _settings_template_context(
            request,
            session,
            form_values,
            message="Account settings updated successfully.",
            errors=[],
            account_form={"new_email": ""},
        ),
    )

@router.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request):
    _log("enter", route="GET /documents")
    session = _get_session(request)
    if not session:
        _log("warn", route="GET /documents", reason="no session -> redirect /login")
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    params = dict(request.query_params)
    _log("info", route="GET /documents", action="redirect_to_settings", params=_safe_map(params))
    return _redirect_documents(**params)


@router.post("/documents/upload")
async def documents_upload(
    request: Request,
    files: list[UploadFile] = File(...),
):
    _log("enter", route="POST /documents/upload")
    session = _get_session(request)
    if not session:
        _log("warn", route="POST /documents/upload", reason="no session -> redirect /login")
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    folder_name = _client_folder_name(session)
    filenames = [f.filename for f in (files or [])]
    _log("files", action="incoming_upload", folder=folder_name, files=filenames)

    if not files or all((file.filename or "").strip() == "" for file in files):
        _log("warn", route="POST /documents/upload", reason="no files selected")
        return _redirect_documents(
            error="Please select at least one file to upload.",
        )

    try:
        result = await rag_docs.upload_documents(folder_name, files)
        _log("files", action="upload_documents", folder=folder_name, result=_safe_map(result))
    except HTTPException as exc:
        detail = str(exc.detail) if exc.detail else "Failed to upload documents."
        _log("error", route="POST /documents/upload", http_error=detail)
        return _redirect_documents(error=detail)
    except ValueError as exc:
        _log("error", route="POST /documents/upload", value_error=str(exc))
        return _redirect_documents(error=str(exc))

    uploaded = result.get("files", [])
    message = f"Uploaded {len(uploaded)} file(s) to '{folder_name}'."
    _log("exit", route="POST /documents/upload", message=message)
    return _redirect_documents(message=message)


@router.post("/documents/files/delete")
async def documents_delete_files(
    request: Request,
    selected_files: list[str] = Form([]),
):
    _log("enter", route="POST /documents/files/delete")
    session = _get_session(request)
    if not session:
        _log("warn", route="POST /documents/files/delete", reason="no session -> redirect /login")
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not selected_files:
        _log("warn", route="POST /documents/files/delete", reason="no files selected")
        return _redirect_documents(error="Select at least one file to delete.")

    folder_name = _client_folder_name(session)
    _log("files", action="delete_request", folder=folder_name, files=selected_files)

    try:
        deleted = rag_docs.delete_files(folder_name, selected_files)
        _log("files", action="delete_files", folder=folder_name, deleted=deleted)
    except FileNotFoundError:
        _log("warn", action="delete_files", folder=folder_name, reason="folder not found")
        return _redirect_documents(error="Client folder not found.")
    except ValueError as exc:
        _log("error", action="delete_files", value_error=str(exc))
        return _redirect_documents(error=str(exc))

    if not deleted:
        _log("warn", action="delete_files", reason="no matching files")
        return _redirect_documents(error="No matching files found to delete.")

    message = f"Deleted {len(deleted)} file(s) from '{folder_name}'."
    _log("exit", route="POST /documents/files/delete", message=message)
    return _redirect_documents(message=message)


@router.post("/documents/ingest")
async def documents_ingest(request: Request):
    _log("enter", route="POST /documents/ingest")
    session = _get_session(request)
    if not session:
        _log("warn", route="POST /documents/ingest", reason="no session -> redirect /login")
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    folder = _client_folder_name(session)
    payload = rag_ingest.IngestRequest(
        folder=folder,
        tenant_id=session["tenant_id"],
    )
    _log("ingest", action="trigger_ingest_start", payload=_safe_map(payload.dict() if hasattr(payload, "dict") else payload.__dict__))

    try:
        result = await rag_ingest.trigger_ingest(payload)
        _log("ingest", action="trigger_ingest_result", result=_safe_map(result))
    except HTTPException as exc:
        detail = str(exc.detail) if exc.detail else "Failed to ingest documents."
        _log("error", route="POST /documents/ingest", http_error=detail)
        return _redirect_documents(error=detail)
    except Exception as exc:  # pragma: no cover - defensive
        _log("error", route="POST /documents/ingest", error=str(exc))
        return _redirect_documents(error=str(exc))

    ingested = result.get("documents_ingested")
    message = f"Number of ingested documents: {engested}" if (engested := result.get("documents_ingested")) is not None else "Ingest completed."
    _log("exit", route="POST /documents/ingest", message=message)
    return _redirect_documents(message=message)


__all__ = ["router"]
