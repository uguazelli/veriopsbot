import os
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app import database
from typing import Annotated

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
    user: str | None = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401)

    await database.upsert_mapping(instance_name, tenant_id)

    # Return just the new row for HTMX to append
    new_mapping = {"instance_name": instance_name, "tenant_id": tenant_id}
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
