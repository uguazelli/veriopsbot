import requests
from sqladmin import ModelView, action
from app.models.clients import Client, IntegrationConfig
from app.core.config import get_settings


settings = get_settings()

class ClientAdmin(ModelView, model=Client):
    column_list = [Client.id, Client.name, Client.slug]
    form_columns = [Client.name, Client.slug]
    icon = "fa-solid fa-users"

class IntegrationConfigAdmin(ModelView, model=IntegrationConfig):
    column_list = [IntegrationConfig.id, IntegrationConfig.client_id, IntegrationConfig.platform_name]
    form_columns = [IntegrationConfig.client, IntegrationConfig.platform_name, IntegrationConfig.settings]
    icon = "fa-solid fa-cogs"

    async def after_model_change(self, data, model, is_created, request):
        if model.platform_name == "telegram":
            token = model.settings.get("bot_token")
            if token:
                # Construct webhook URL using the request's base URL (requires proxy headers to be trusted)
                # request.base_url encompasses scheme and netloc (e.g. https://dev-bot.veridatapro.com/)
                base_url = str(request.base_url).rstrip("/")
                webhook_url = f"{base_url}/webhook/telegram/{token}"

                try:
                    resp = requests.post(f"https://api.telegram.org/bot{token}/setWebhook", data={"url": webhook_url}, timeout=10)
                    resp.raise_for_status()
                    print(f"Auto-configured webhook for {model}: {webhook_url}")
                except Exception as e:
                    print(f"Failed to auto-configure webhook for {model}: {e}")
