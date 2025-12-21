from fastapi import APIRouter, Request, Form, Response, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app import database
import os

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

EVOLUTION_URL = os.getenv("EVOLUTION_URL", "https://dev-evolution.veridatapro.com")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")

# --- Dependency ---
async def get_current_user_instance(request: Request):
    instance_name = request.cookies.get("user_session")
    if not instance_name:
        return None
    return instance_name

# --- Routes ---

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("user_login.html", {"request": request})

@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    instance_name: str = Form(...),
    access_key: str = Form(...)
):
    instance_name = instance_name.strip()
    access_key = access_key.strip()

    is_valid = await database.verify_user_login(instance_name, access_key)

    if is_valid:
        response = RedirectResponse(url="/user", status_code=303)
        # In a real app, sign this cookie or use session middleware
        response.set_cookie(key="user_session", value=instance_name, httponly=True, max_age=86400 * 30)
        return response

    return templates.TemplateResponse("user_login.html", {
        "request": request,
        "error": "Invalid Instance Name or Access Key",
        "instance_name": instance_name
    })

@router.post("/user/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("user_session")
    return response

@router.get("/user", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    instance_name: str | None = Depends(get_current_user_instance)
):
    if not instance_name:
        return RedirectResponse(url="/login")

    all_sessions = await database.get_all_sessions()
    # Filter for this instance
    my_sessions = [s for s in all_sessions if s['instance_name'] == instance_name]

    # Get Global Status
    is_globally_active = await database.get_instance_status(instance_name)

    # Get Quota Stats
    quota = await database.check_rate_limit(instance_name)

    return templates.TemplateResponse("user_dashboard.html", {
        "request": request,
        "instance_name": instance_name,
        "sessions": my_sessions,
        "is_globally_active": is_globally_active,
        "quota": quota
    })

@router.post("/user/toggle/{phone_number}")
async def toggle_session(
    request: Request,
    phone_number: str,
    instance_name: str | None = Depends(get_current_user_instance)
):
    if not instance_name:
        return Response(status_code=401)

    # Get current status to flip it
    current = await database.get_session_status(instance_name, phone_number)
    new_status = not current

    await database.set_session_active(instance_name, phone_number, new_status)

    all_sessions = await database.get_all_sessions()
    updated_session = next((s for s in all_sessions if s['instance_name'] == instance_name and s['phone_number'] == phone_number), None)

    if not updated_session:
        # Fallback if something weird happened
        from datetime import datetime
        updated_session = {"phone_number": phone_number, "is_active": new_status, "instance_name": instance_name, "updated_at": datetime.now()}

    return templates.TemplateResponse("partials/user_session_row.html", {"request": request, "session": updated_session})


@router.post("/user/toggle_global")
async def toggle_global(
    request: Request,
    instance_name: str | None = Depends(get_current_user_instance)
):
    if not instance_name:
        return Response(status_code=401)

    current_status = await database.get_instance_status(instance_name)
    new_status = not current_status

    await database.set_instance_status(instance_name, new_status)

    # Return JUST the button to sway via HTMX
    # We can use an inline template string or a partial.
    # Let's use a partial for cleanliness.
    return templates.TemplateResponse("partials/global_toggle_btn.html", {
        "request": request,
        "is_globally_active": new_status
    })
