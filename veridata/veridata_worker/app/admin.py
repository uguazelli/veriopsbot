from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse
import logging
from app.database import settings, get_session
from app.models import Client, SyncConfig, ServiceConfig, Subscription, BotSession
from app.jobs.auto_resolve import run_auto_resolve_job

class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username, password = form.get("username"), form.get("password")

        # Basic env-based auth
        if username == settings.ADMIN_USER and password == settings.ADMIN_PASSWORD:
            request.session.update({"token": "admin-token"})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.session.get("token")
        return bool(token)

authentication_backend = AdminAuth(secret_key="secret-key") # TODO: Move secret to settings

class ClientAdmin(ModelView, model=Client):
    name = "Client / Tenant"
    name_plural = "Clients / Tenants"
    column_list = [Client.id, Client.name, Client.slug, Client.is_active]
    can_create = True
    can_edit = True
    can_delete = True
    icon = "fa-solid fa-users"

class SyncConfigAdmin(ModelView, model=SyncConfig):
    name = "Job Schedule"
    name_plural = "Job Schedules"
    column_list = [SyncConfig.id, SyncConfig.client_id, SyncConfig.platform, SyncConfig.is_active]
    form_columns = [SyncConfig.client, SyncConfig.platform, SyncConfig.config_json, SyncConfig.is_active, SyncConfig.frequency_minutes]
    icon = "fa-solid fa-gears"

    @action("run_now", "Execute Now", add_in_detail=True, add_in_list=True)
    async def run_now(self, request: Request):
        pks = request.query_params.get("pks", "").split(",")
        if pks:
            async for session in get_session():
                for pk in pks:
                    try:
                        config = await session.get(SyncConfig, int(pk))
                        if config and (config.platform == "chatwoot" or config.platform == "chatwoot-auto-resolve"):
                            await run_auto_resolve_job(session, config)
                    except Exception as e:
                        logging.error(f"Failed to run job {pk}: {e}")

        referer = request.headers.get("referer")
        if referer:
            return RedirectResponse(referer)
        return RedirectResponse(request.url_for("admin:list", identity="syncconfig"))

class ServiceConfigAdmin(ModelView, model=ServiceConfig):
    name = "Service Credential"
    name_plural = "Service Credentials"
    column_list = [ServiceConfig.id, ServiceConfig.client_id, ServiceConfig.platform]
    form_columns = [ServiceConfig.client, ServiceConfig.platform, ServiceConfig.config]
    icon = "fa-solid fa-robot"

class SubscriptionAdmin(ModelView, model=Subscription):
    name = "Usage Quota"
    name_plural = "Usage Quotas"
    column_list = [Subscription.id, Subscription.client_id, Subscription.quota_limit, Subscription.usage_count, Subscription.start_date, Subscription.end_date]
    form_columns = [Subscription.client, Subscription.quota_limit, Subscription.usage_count, Subscription.start_date, Subscription.end_date]
    icon = "fa-solid fa-file-invoice"

class BotSessionAdmin(ModelView, model=BotSession):
    can_create = False
    name = "Live Session"
    name_plural = "Live Sessions"
    column_list = [BotSession.id, BotSession.client_id, BotSession.external_session_id, BotSession.rag_session_id]
    icon = "fa-solid fa-comments"
