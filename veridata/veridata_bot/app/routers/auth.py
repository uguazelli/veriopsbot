from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    # Simple check against env vars for Admin
    if username == settings.ADMIN_USER and password == settings.ADMIN_PASSWORD:
         # Set session or cookie
         response = Response(status_code=200)
         response.headers["HX-Redirect"] = "/admin/dashboard"
         response.set_cookie(key="access_token", value=f"bearer admin_token", httponly=True)
         return response

    # TODO: Check against DB for other users

    return HTMLResponse('<div class="alert">Invalid credentials</div>', status_code=401)

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
