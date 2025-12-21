import os
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app import database

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")

ADMIN_USERNAME = os.getenv("ADMIN_USER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Dependency to check auth
async def get_current_user(request: Request):
    session = request.cookies.get("admin_session")
    if not session or session != "authenticated":
        return None
    return "admin"

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="admin_session", value="authenticated", httponly=True)
        return response

    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("admin_session")
    return response

@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: str | None = Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/admin/login")

    mappings = await database.get_all_mappings()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "mappings": mappings
    })

@router.post("/mappings", response_class=HTMLResponse)
async def add_mapping(
    request: Request,
    instance_name: str = Form(...),
    tenant_id: str = Form(...),
    access_key: str = Form(None),
    platform_token: str = Form(None),
    message_limit: int = Form(1000),
    renewal_date: str = Form(None),
    user: str | None = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401)

    # Sanitize inputs
    instance_name = instance_name.strip()
    tenant_id = tenant_id.strip()

    access_key = access_key.strip() if access_key else None
    platform_token = platform_token.strip() if platform_token else None

    # Empty string renewal_date should be None
    renewal_date_obj = None
    if renewal_date and renewal_date.strip():
        try:
            renewal_date_obj = datetime.strptime(renewal_date, "%Y-%m-%d").date()
        except ValueError:
            pass # Or handle error. For now, ignore invalid dates.

    # Logic: If platform_token is provided, instance_name is the ALIAS.
    # Otherwise, instance_name IS the platform ID (Evolution).

    await database.upsert_mapping(
        instance_name,
        tenant_id,
        access_key,
        platform_token,
        message_limit=message_limit,
        renewal_date=renewal_date_obj
    )

    # Telegram Webhook Registration
    # Condition: It has a platform_token (Explicit Telegram) OR instance_name looks like a token (Old way)
    # AND it is not a Chatwoot instance.
    telegram_token = None
    if not instance_name.startswith("chatwoot_"):
        telegram_token = platform_token
        if not telegram_token and ":" in instance_name and len(instance_name) > 20:
            telegram_token = instance_name

    if telegram_token:
        # We need the base URL of this server.
        base_url = os.getenv("PUBLIC_URL") or os.getenv("VERIDATA_BOT_URL") or str(request.base_url).rstrip("/")
        base_url = base_url.rstrip("/")

        # Webhook URL uses the INSTANCE NAME (Alias), not the token
        webhook_url = f"{base_url}/telegram/webhook/{instance_name}"

        print(f"🤖 Telegram Bot detected. Setting webhook for alias '{instance_name}' to: {webhook_url}")

        try:
            import httpx
            tg_url = f"https://api.telegram.org/bot{telegram_token}/setWebhook"
            async with httpx.AsyncClient() as client:
                resp = await client.post(tg_url, json={"url": webhook_url})
                print(f"📡 Telegram setWebhook response: {resp.text}")
        except Exception as e:
            print(f"⚠️ Failed to auto-set Telegram webhook: {e}")

    # Return just the new row for HTMX to append
    # Refetch to get calculated fields (like renewal_date default)
    mappings = await database.get_all_mappings()
    new_mapping = next((m for m in mappings if m['instance_name'] == instance_name), None)

    return templates.TemplateResponse("partials/mapping_row.html", {
        "request": request,
        "mapping": new_mapping
    })

@router.delete("/mappings/{instance_name}")
async def delete_mapping_endpoint(
    instance_name: str,
    user: str | None = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401)

    await database.delete_mapping(instance_name)
    return HTMLResponse(content="") # Return empty to remove element from DOM

@router.get("/sessions", response_class=HTMLResponse)
async def sessions_page(
    request: Request,
    user: str | None = Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/admin/login")

    sessions = await database.get_all_sessions()
    return templates.TemplateResponse("sessions.html", {
        "request": request,
        "sessions": sessions
    })

@router.delete("/sessions/{instance_name}/{phone_number}")
async def delete_session_endpoint(
    instance_name: str,
    phone_number: str,
    user: str | None = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401)

    await database.delete_session(instance_name, phone_number)
    return HTMLResponse(content="")

@router.post("/sessions/toggle/{instance_name}/{phone_number}")
async def toggle_session_endpoint(
    request: Request,
    instance_name: str,
    phone_number: str,
    user: str | None = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401)

    # Get current status to flip it
    current = await database.get_session_status(instance_name, phone_number)
    new_status = not current

    await database.set_session_active(instance_name, phone_number, new_status)

    # Re-fetch the updated session to ensure correct timestamp etc.
    all_sessions = await database.get_all_sessions()
    updated_session = next((s for s in all_sessions if s['instance_name'] == instance_name and s['phone_number'] == phone_number), None)

    if not updated_session:
         # Fallback (though unlikely if we just updated it)
        from datetime import datetime
        updated_session = {
            "instance_name": instance_name,
            "phone_number": phone_number,
            "is_active": new_status,
            "updated_at": datetime.now(),
            "session_id": "..."
        }

    return templates.TemplateResponse("partials/session_row.html", {"request": request, "session": updated_session})


@router.post("/mappings/toggle_global/{instance_name}")
async def toggle_global_mapping(
    request: Request,
    instance_name: str,
    user: str | None = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401)

    current_status = await database.get_instance_status(instance_name)
    new_status = not current_status

    await database.set_instance_status(instance_name, new_status)

    # Return updated mapping row partial
    # We need to construct the mapping object again
    # Simplest way is refetch all and find it, or just manual dict construction if we trust inputs
    # Let's refetch to be safe and consistent
    mappings = await database.get_all_mappings()
    updated_mapping = next((m for m in mappings if m['instance_name'] == instance_name), None)

    if updated_mapping:
        return templates.TemplateResponse("partials/mapping_row.html", {
            "request": request,
            "mapping": updated_mapping
        })
    else:
        return Response(status_code=404)
