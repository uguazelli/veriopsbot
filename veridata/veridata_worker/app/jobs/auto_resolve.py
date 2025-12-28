from datetime import datetime, timezone
import logging
from app.models import SyncConfig
from app.integrations.chatwoot import ChatwootClient

logger = logging.getLogger(__name__)

async def run_auto_resolve_job(config: SyncConfig):
    """
    Checks for inactive conversations and resolves them.
    Triggered by SyncConfig with platform='chatwoot-auto-resolve'.
    """
    logger.info(f"Starting Auto-Resolve Job for Config ID {config.id}")

    # Extract settings
    cw_config = config.config_json
    base_url = cw_config.get("base_url")
    account_id = cw_config.get("account_id")
    access_token = cw_config.get("access_token")

    if not all([base_url, account_id, access_token]):
        logger.error(f"Missing Chatwoot connection details in Config {config.id}")
        return

    client = ChatwootClient(base_url, account_id, access_token)

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
