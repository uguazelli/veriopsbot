import logging

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.summarizer import summarize_start_conversation
from app.core.logging import log_db, log_error, log_external_call, log_skip, log_start, log_success
from app.integrations.chatwoot import ChatwootClient
from app.integrations.crm.espocrm import EspoClient
from app.integrations.crm.hubspot import HubSpotClient
from app.integrations.rag import RagClient
from app.models import BotSession, Client, ServiceConfig, Subscription

import datetime
from app.integrations.transcription import transcribe_audio

logger = logging.getLogger(__name__)


# ==================================================================================
# ACTION: GET CLIENT & CONFIG
# Helper to fetch the Tenant and its Secrets (API Keys) from DB
# ==================================================================================
async def get_client_and_config(client_slug: str, db: AsyncSession):
    query = select(Client).where(Client.slug == client_slug, Client.is_active == True)
    result = await db.execute(query)
    client = result.scalars().first()

    if not client:
        log_error(logger, f"Client not found or inactive: {client_slug}")
        raise HTTPException(status_code=404, detail="Client not found or inactive")

    cfg_query = select(ServiceConfig).where(ServiceConfig.client_id == client.id)
    cfg_result = await db.execute(cfg_query)
    cfg_record = cfg_result.scalars().first()
    configs = cfg_record.config if cfg_record else {}

    return client, configs


# ==================================================================================
# ACTION: LOAD CRM CLIENTS
# Creates instances of HubSpot/EspoCRM clients based on config.
# returns a list of active clients.
# ==================================================================================
def get_crm_integrations(configs):
    integrations = []

    espo_conf = configs.get("espocrm")
    if espo_conf:
        integrations.append(EspoClient(base_url=espo_conf["base_url"], api_key=espo_conf["api_key"]))

    hub_conf = configs.get("hubspot")
    if hub_conf:
        token = hub_conf.get("access_token") or hub_conf.get("api_key")
        if token:
            integrations.append(HubSpotClient(access_token=token))

    return integrations


# ==================================================================================
# ACTION: CHECK QUOTA
# Verifies if the client has enough credits left in their subscription.
# ==================================================================================
async def check_subscription_quota(client_id, client_slug, db: AsyncSession):
    sub_query = select(Subscription).where(
        Subscription.client_id == client_id, Subscription.usage_count < Subscription.quota_limit
    )
    result = await db.execute(sub_query)
    subscription = result.scalars().first()

    if not subscription:
        log_error(logger, f"Subscription limit reached for {client_slug}")
        return None

    return subscription


# ==================================================================================
# ACTION: EXECUTE CRM ACTION
# Generic wrapper to run a function on ALL connected CRMs sequentially.
# E.g. "Save Lead" -> saves to both HubSpot and Espo if configured.
# ==================================================================================
async def execute_crm_action(crms, action_desc, action_func):
    if not crms:
        log_skip(logger, f"Skipping CRM sync ({action_desc}): No CRM configured")
        return

    log_external_call(logger, "CRM", f"Syncing {action_desc} to {len(crms)} integrations")
    for crm in crms:
        platform_name = crm.__class__.__name__.replace("Client", "")
        try:
            await action_func(crm)
            log_success(logger, f"{action_desc} synced: {platform_name}")
        except Exception as e:
            log_error(logger, f"CRM Sync failed for {platform_name}: {e}")


# ==================================================================================
# ACTION: EXECUTE RAG QUERY (Unused - moved to Agent Node)
# Kept for reference or direct calls bypassing the agent.
# ==================================================================================
async def query_rag_system(user_query, session, rag_config) -> dict:
    rag_provider = rag_config.get("provider")
    rag_use_hyde = rag_config.get("use_hyde")
    rag_use_rerank = rag_config.get("use_rerank")

    rag_client = RagClient(
        base_url=rag_config["base_url"], api_key=rag_config.get("api_key", ""), tenant_id=rag_config["tenant_id"]
    )

    try:
        query_params = {}
        if rag_provider:
            query_params["provider"] = rag_provider
        if rag_use_hyde is not None:
            query_params["use_hyde"] = rag_use_hyde
        if rag_use_rerank is not None:
            query_params["use_rerank"] = rag_use_rerank
        handoff_rules = rag_config.get("handoff_rules")
        if handoff_rules:
            query_params["handoff_rules"] = handoff_rules

        gs_url = rag_config.get("google_sheets_url")
        if gs_url:
            query_params["google_sheets_url"] = gs_url

        log_external_call(logger, "Veridata RAG", f"Query: '{user_query}' | Params: {query_params}")
        rag_response = await rag_client.query(message=user_query, session_id=session.rag_session_id, **query_params)
        log_success(logger, "RAG response received successfully")
        return rag_response
    except Exception as e:
        log_error(logger, f"RAG Error: {e}", exc_info=True)
        return {"error": str(e)}


# ==================================================================================
# ACTION: HANDLE AUDIO
# Downloads audio from Chatwoot URL -> Transcribes via OpenAI/Gemini
# ==================================================================================
async def handle_audio_message(attachments, rag_config) -> str:
    if not attachments:
        return ""

    for att in attachments:
        logger.info(f"Processing attachment: type={att.file_type}, url={att.data_url}")

        if att.file_type == "audio":
            filename = f"audio.{att.extension or 'mp3'}"
            logger.info(f"Found audio attachment. Downloading from: {att.data_url}")

            try:
                async with httpx.AsyncClient(follow_redirects=True) as http_client:
                    log_external_call(logger, "Internal/Web", f"Downloading audio from {att.data_url}")
                    resp = await http_client.get(att.data_url)
                    resp.raise_for_status()
                    audio_bytes = resp.content
                    logger.info(f"Download complete. Size: {len(audio_bytes)} bytes")

                    # Transcribe locally


                    transcript_text = await transcribe_audio(audio_bytes, att.data_url)

                    logger.info(f"Transcription result: {transcript_text}")
                    return transcript_text

            except Exception as e:
                log_error(logger, f"Failed to process audio attachment: {e}")
                return ""

    return ""


# ==================================================================================
# ACTION: SEND REPLY TO CHATWOOT
# Posts the final AI answer back to the conversation.
# Also handles toggling status to 'Open' (Handover) or 'Pending' (Bot active).
# ==================================================================================
async def handle_chatwoot_response(conversation_id, answer, requires_human, chatwoot_config):
    cw_client = ChatwootClient(
        base_url=chatwoot_config["base_url"],
        api_token=chatwoot_config["api_key"],
        account_id=chatwoot_config.get("account_id", 1),
    )

    if answer:
        log_external_call(logger, "Chatwoot", f"Sending response to conversation {conversation_id}")
        await cw_client.send_message(conversation_id=conversation_id, message=answer)
        log_success(logger, "Response sent to Chatwoot")
    else:
        log_skip(logger, "RAG returned no answer (empty response)")

    try:
        if requires_human:
            log_start(logger, f"Handover requested for session {conversation_id}")
            await cw_client.toggle_status(conversation_id, "open")
            log_success(logger, "Conversation opened for human agent")

        else:
            log_external_call(logger, "Chatwoot", f"Enforcing pending status for conversation {conversation_id}")
            await cw_client.toggle_status(conversation_id, "pending")
            log_success(logger, "Conversation set to pending")

    except Exception as e:
        log_error(logger, f"Failed to update status for {conversation_id}: {e}")


# ==================================================================================
# ACTION: RESOLVE & SUMMARIZE
# Triggered when conversation is marked 'Resolved'.
# Generates a summary and syncs it to the CRM.
# ==================================================================================
async def handle_conversation_resolution(client, configs, conversation_data, sender, db):
    conversation_id = str(conversation_data.get("id"))
    client_slug = client.slug

    log_db(logger, f"Looking for BotSession for resolution. Ext ID: '{conversation_id}'")

    session_query = select(BotSession).where(
        BotSession.client_id == client.id, BotSession.external_session_id == conversation_id
    )
    sess_result = await db.execute(session_query)
    session = sess_result.scalars().first()

    if session and session.rag_session_id:
        rag_config = configs.get("rag")
        if rag_config:
            try:
                rag_client = RagClient(
                    base_url=rag_config["base_url"],
                    api_key=rag_config.get("api_key", ""),
                    tenant_id=rag_config["tenant_id"],
                )

                # New Local Summarization Flow
                target_lang = configs.get("client_config", {}).get("summary_language")
                summary = await summarize_start_conversation(
                    session_id=session.rag_session_id,
                    rag_client=rag_client,
                    language_instruction=target_lang
                )
                log_success(logger, "Summary generated successfully (Local LLM)")

                # import datetime (removed)

                # 1. Try to get start time from RAG history (Real Session Start)
                rag_start_str = summary.get("session_start_time")
                start_str = "Unknown"

                if rag_start_str:
                    # Parse ISO format from RAG (e.g., 2026-01-11T12:00:00+00:00)
                    try:
                        # Handle ISO format
                        start_dt = datetime.datetime.fromisoformat(rag_start_str)
                        start_str = start_dt.strftime("%d/%m/%Y %H:%M")
                    except ValueError as e:
                        logger.warning(f"Failed to parse RAG timestamp: {rag_start_str} | Error: {e}")

                # 2. Fallback to Chatwoot Conversation Create Date
                if start_str == "Unknown":
                    created_at_ts = conversation_data.get("created_at")
                    if created_at_ts:
                        try:
                            start_dt = datetime.datetime.fromtimestamp(int(created_at_ts))
                            start_str = start_dt.strftime("%d/%m/%Y %H:%M")
                        except Exception:
                            pass

                now = datetime.datetime.now()

                end_str = now.strftime("%d/%m/%Y %H:%M")

                summary["conversation_start"] = start_str
                summary["conversation_end"] = end_str

                crms = get_crm_integrations(configs)
                if crms:
                    pass

                    if sender and (sender.email or sender.phone_number):
                        await execute_crm_action(
                            crms,
                            "conversation summary",
                            lambda crm: crm.update_lead_summary(sender.email, sender.phone_number, summary),
                        )
                    else:
                        log_skip(logger, "Skipping CRM update: No email or phone to match lead")

                try:
                    log_external_call(logger, "Veridata RAG", f"Deleting RAG session {session.rag_session_id}")
                    await rag_client.delete_session(session.rag_session_id)
                except Exception as e:
                    log_error(logger, f"Failed to delete RAG session: {e}")

                log_db(logger, f"Deleting BotSession {session.id} for resolved conversation")
                await db.delete(session)
                await db.commit()

            except Exception as e:
                log_error(logger, f"Summarization flow failed: {e}", exc_info=True)
        else:
            log_skip(logger, "RAG config missing, cannot summarize")
    else:
        log_skip(logger, "No active BotSession found for this conversation, skipping summary.")
