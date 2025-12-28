from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse
import logging
from app.database import settings
from app.models import Client, SyncConfig, ServiceConfig, Subscription, BotSession

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
    column_list = [Client.id, Client.name, Client.slug, Client.is_active]
    can_create = False # Reuse existing
    can_edit = False   # Reuse existing
    can_delete = False # Reuse existing
    icon = "fa-solid fa-users"

class SyncConfigAdmin(ModelView, model=SyncConfig):
    name = "Worker Job Config"
    name_plural = "Worker Job Configs"
    column_list = [SyncConfig.id, SyncConfig.client_id, SyncConfig.platform, SyncConfig.is_active]
    form_columns = [SyncConfig.client, SyncConfig.platform, SyncConfig.config_json, SyncConfig.is_active, SyncConfig.frequency_minutes]
    icon = "fa-solid fa-gears"

class ServiceConfigAdmin(ModelView, model=ServiceConfig):
    name = "Bot Service Config"
    name_plural = "Bot Service Configs"
    column_list = [ServiceConfig.id, ServiceConfig.client_id, ServiceConfig.platform]
    form_columns = [ServiceConfig.client, ServiceConfig.platform, ServiceConfig.config]
    icon = "fa-solid fa-robot"

class SubscriptionAdmin(ModelView, model=Subscription):
    column_list = [Subscription.id, Subscription.client_id, Subscription.quota_limit, Subscription.usage_count]
    form_columns = [Subscription.client, Subscription.quota_limit, Subscription.usage_count]
    icon = "fa-solid fa-file-invoice"

class BotSessionAdmin(ModelView, model=BotSession):
    can_create = False
    name = "Active Bot Session"
    name_plural = "Active Bot Sessions"
    column_list = [BotSession.id, BotSession.client_id, BotSession.external_session_id, BotSession.rag_session_id]
    icon = "fa-solid fa-comments"
