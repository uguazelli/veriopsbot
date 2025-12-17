from fastapi import FastAPI, Depends, HTTPException, Header
from sqladmin import Admin, ModelView
from app.database import engine, init_db, get_session
from app.models import Client, IntegrationSource, IntegrationDestination, IdentityMap
from app.schemas import LeadCreateSchema
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
import httpx


app = FastAPI(title="Veridata Integrator")

class ClientAdmin(ModelView, model=Client):
    column_list = [Client.id, Client.name, Client.api_key, Client.rag_tenant_id, Client.bot_instance_alias]

class SourceAdmin(ModelView, model=IntegrationSource):
    column_list = [IntegrationSource.id, IntegrationSource.type, IntegrationSource.client]

class DestinationAdmin(ModelView, model=IntegrationDestination):
    column_list = [IntegrationDestination.id, IntegrationDestination.type, IntegrationDestination.client]

class IdentityMapAdmin(ModelView, model=IdentityMap):
    column_list = [IdentityMap.id, IdentityMap.source_user_ref, IdentityMap.destination_lead_ref]

admin = Admin(app, engine)
admin.add_view(ClientAdmin)
admin.add_view(SourceAdmin)
admin.add_view(DestinationAdmin)
admin.add_view(IdentityMapAdmin)

@app.on_event("startup")
async def on_startup():
    await init_db()

async def get_client_by_key(
    x_veridata_client_key: str = Header(...),
    session: AsyncSession = Depends(get_session)
) -> Client:
    statement = select(Client).where(Client.api_key == x_veridata_client_key)
    result = await session.exec(statement)
    client = result.first()
    if not client:
        raise HTTPException(status_code=401, detail="Invalid Client Key")
    return client

@app.post("/api/v1/leads")
async def create_lead(
    lead_data: LeadCreateSchema,
    client: Client = Depends(get_client_by_key),
    session: AsyncSession = Depends(get_session)
):
    # 1. Find EspoCRM destination for this client
    # We implicitly assume one EspoCRM destination per client for now, or take the first one.
    statement = select(IntegrationDestination).where(
        IntegrationDestination.client_id == client.id,
        IntegrationDestination.type == "espocrm"
    )
    result = await session.exec(statement)
    destination = result.first()

    if not destination:
        raise HTTPException(status_code=404, detail="EspoCRM destination not configured for this client")

    config = destination.config
    base_url = config.get("url")
    api_key = config.get("api_key")

    if not base_url or not api_key:
        raise HTTPException(status_code=500, detail="Invalid EspoCRM configuration")

    # Ensure slash in url
    if not base_url.endswith("/"):
        base_url += "/"

    target_url = f"{base_url}api/v1/Lead"

    # 2. Forward request to EspoCRM
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as ac:
        try:
            response = await ac.post(target_url, json=lead_data.model_dump(), headers=headers)
        except Exception as e:
             raise HTTPException(status_code=502, detail=f"Failed to connect to EspoCRM: {str(e)}")

    if response.status_code >= 400:
         return {
             "status": "error",
             "upstream_status": response.status_code,
             "detail": response.text
         }

    crm_data = response.json()
    crm_id = crm_data.get("id")

    # 3. Create Identity Map (Optional logic: if we want to track this automatically)
    # The user didn't explicitly ask to SAVE the mapping here, but it's part of the goal.
    # However, to save mapping we need a Source ID and Source User Ref.
    # The input JSON has 'phoneNumber', which could be the ref.
    # But we don't know the 'IntegrationSource' this came from unless we pass it or infer it.
    # For now, we will just proxy and return the result as requested.

    return crm_data

@app.get("/health")
def health_check():
    return {"status": "ok"}
