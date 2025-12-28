from datetime import datetime, timezone
import logging
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models import SyncConfig, ServiceConfig
from app.integrations.chatwoot import ChatwootClient

logger = logging.getLogger(__name__)

async def run_auto_resolve_job(session: AsyncSession, config: SyncConfig):
    """
    Checks for inactive conversations and resolves them.
    Triggered by SyncConfig. Platform credentials fetched from ServiceConfig.
    """
    logger.info(f"Starting Auto-Resolve Job for Config ID {config.id}")

    # 1. Fetch Credentials from ServiceConfig
    # We look for the 'chatwoot' service config for this client
    stmt = select(ServiceConfig).where(
        ServiceConfig.client_id == config.client_id,
        ServiceConfig.platform == "chatwoot"
    )
    result = await session.execute(stmt)
    service_config = result.scalars().first()

    if not service_config:
        logger.error(f"Skipping Auto-Resolve for Config {config.id}: No 'chatwoot' ServiceConfig found for Client {config.client_id}")
        return

    cw_creds = service_config.config
    base_url = cw_creds.get("base_url")
    account_id = cw_creds.get("account_id", "1")
    access_token = cw_creds.get("api_key") # Map 'api_key' to access_token

    if not all([base_url, access_token]):
        logger.error(f"Invalid Chatwoot credentials in ServiceConfig {service_config.id}")
        return

    client = ChatwootClient(base_url, str(account_id), access_token)

    # Fetch OPEN conversations
    # (Checking 'pending' too might be good, but starting with 'open' is safer)
    conversations = await client.get_conversations(status="open")

    now = datetime.now(timezone.utc).timestamp() # Current unix timestamp
    threshold_seconds = config.frequency_minutes * 60

    resolve_count = 0

    for conv in conversations:
        # last_activity_at is a unix timestamp in Chatwoot (usually)
        # Verify format: "last_activity_at": 1709230232
        last_activity = conv.get("last_activity_at")

        if not last_activity:
            continue

        try:
            last_activity_ts = float(last_activity)

            # Check Inactivity
            if (now - last_activity_ts) > threshold_seconds:
                conv_id = conv.get("id")
                logger.info(f"Conversation {conv_id} inactive for {(now - last_activity_ts)/60:.1f} mins. Resolving...")

                await client.toggle_status(conv_id, "resolved")
                resolve_count += 1

        except Exception as e:
            logger.warning(f"Error processing conversation {conv.get('id')}: {e}")

    if resolve_count > 0:
        logger.info(f"Auto-Resolve Job Complete. Resolved {resolve_count} conversations.")
    else:
        logger.info("Auto-Resolve Job Complete. No inactive conversations found.")
