from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.database import get_db
from app.models.integration import IntegrationConfig
from app.models.client import Client
from app.core.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")

async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token or token != "bearer admin_token":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return "admin"

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Redirect to clients list as dashboard
    return RedirectResponse(url="/admin/clients", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/clients", response_class=HTMLResponse)
async def list_clients(
    request: Request,
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client))
    clients = result.scalars().all()
    return templates.TemplateResponse("admin_clients.html", {"request": request, "clients": clients})

@router.post("/clients/create")
async def create_client(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Check if slug exists
    exists = await db.execute(select(Client).where(Client.slug == slug))
    if exists.scalar_one_or_none():
        return HTMLResponse("<div class='alert'>Slug already exists</div>")

    new_client = Client(name=name, slug=slug, extra_settings={})
    db.add(new_client)
    await db.commit()
    await db.refresh(new_client)

    return HTMLResponse(f"""
        <div class="card" style="margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <strong>{new_client.name}</strong> <small>({new_client.slug})</small>
            </div>
            <div>
                 <a href="/admin/clients/{new_client.id}/integrations" class="btn" style="font-size: 0.8rem;">Manage Integrations</a>
            </div>
        </div>
    """)

@router.get("/clients/{client_id}/integrations", response_class=HTMLResponse)
async def manage_integrations(
    request: Request,
    client_id: int,
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    client = await db.get(Client, client_id)
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    # tailored query to fetch all integrations for this client
    result = await db.execute(select(IntegrationConfig).where(IntegrationConfig.client_id == client_id))
    configs = result.scalars().all()

    # Transform configs list into a dict keyed by platform for easy access in template
    integrations_map = {}
    for config in configs:
        # Pydantic or dict access for JSONB? SQLAlchemy returns dict for JSONB usually
        integrations_map[config.platform] = config.settings

    return templates.TemplateResponse("client_integrations.html", {
        "request": request,
        "client": client,
        "integrations": integrations_map
    })

@router.post("/clients/{client_id}/integrations/{platform}")
async def save_integration(
    request: Request,
    client_id: int,
    platform: str,
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    form_data = await request.form()
    # Filter out empty strings if needed, or keep them to clear config
    settings_dict = {k: v for k, v in form_data.items()}

    # Check if config exists
    result = await db.execute(select(IntegrationConfig).where(
        IntegrationConfig.client_id == client_id,
        IntegrationConfig.platform == platform
    ))
    config = result.scalar_one_or_none()

    if config:
        config.settings = settings_dict
    else:
        config = IntegrationConfig(client_id=client_id, platform=platform, settings=settings_dict)
        db.add(config)

    await db.commit()

    return HTMLResponse(f"""
        <div style="position: fixed; top: 20px; right: 20px; background: green; color: white; padding: 1rem; border-radius: 4px; animation: fadeOut 3s forwards;">
            Saved {platform} settings!
        </div>
        <style>@keyframes fadeOut {{ 0% {{ opacity: 1; }} 100% {{ opacity: 0; }} }}</style>
    """)
