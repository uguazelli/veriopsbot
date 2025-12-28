from datetime import datetime, timezone
import logging
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models import SyncConfig, ServiceConfig
from app.integrations.chatwoot import ChatwootClient
from app.core.logging import log_start, log_success, log_error, log_job, log_external_call

logger = logging.getLogger(__name__)

async def run_auto_resolve_job(session: AsyncSession, config: SyncConfig):
    """
    Checks for inactive conversations and resolves them.
    Triggered by SyncConfig. Platform credentials fetched from ServiceConfig.
    """
    log_start(logger, f"Starting Auto-Resolve Job for Config ID {config.id}")

    # 1. Fetch Credentials from ServiceConfig
    # We look for the 'chatwoot' service config for this client
    stmt = select(ServiceConfig).where(
        ServiceConfig.client_id == config.client_id,
        ServiceConfig.platform == "chatwoot"
    )
    result = await session.execute(stmt)
    service_config = result.scalars().first()

    if not service_config:
        log_error(logger, f"Skipping Auto-Resolve for Config {config.id}: No 'chatwoot' ServiceConfig found for Client {config.client_id}")
        return

    cw_creds = service_config.config
    base_url = cw_creds.get("base_url")
    account_id = cw_creds.get("account_id", "1")
    access_token = cw_creds.get("api_key") # Map 'api_key' to access_token

    if not all([base_url, access_token]):
        log_error(logger, f"Invalid Chatwoot credentials in ServiceConfig {service_config.id}")
        return

    client = ChatwootClient(base_url, str(account_id), access_token)

    # Fetch OPEN and PENDING conversations
    log_external_call(logger, "Chatwoot", "Fetching open/pending conversations")
    conversations_open = await client.get_conversations(status="open")
    conversations_pending = await client.get_conversations(status="pending")

    conversations = conversations_open + conversations_pending

    now = datetime.now(timezone.utc).timestamp() # Current unix timestamp

    # Use inactivity_threshold_minutes if set, otherwise fallback to 30 mins
    inactivity_mins = config.inactivity_threshold_minutes if config.inactivity_threshold_minutes is not None else 30
    threshold_seconds = inactivity_mins * 60

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
                log_job(logger, f"Conversation {conv_id} inactive for {(now - last_activity_ts)/60:.1f} mins (Threshold: {inactivity_mins}m). Resolving...")

                await client.toggle_status(conv_id, "resolved")
                resolve_count += 1

        except Exception as e:
            log_error(logger, f"Error processing conversation {conv.get('id')}: {e}")

    if resolve_count > 0:
        log_success(logger, f"Auto-Resolve Job Complete. Resolved {resolve_count} conversations.")
    else:
        log_success(logger, "Auto-Resolve Job Complete. No inactive conversations found.")
