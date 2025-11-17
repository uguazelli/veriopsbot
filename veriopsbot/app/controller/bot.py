"""Chatwoot bot controller logic."""

from datetime import date
import logging

import httpx

from app.chatwoot.handoff import perform_handoff, send_message
from app.db.repository import (
    get_bot_request_total,
    get_params_by_omnichannel_id,
    increment_bot_request_count,
)
from app.rag_engine.rag import handle_input, initial_state


SESSIONS: dict[str, dict] = {}

logger = logging.getLogger("veriops.bot")


async def process_bot_request(data: dict):
    convo = data.get("conversation", {}) or {}
    assignee_id = (convo.get("meta", {}) or {}).get("assignee", {}) or {}
    assignee_id = assignee_id.get("id")

    if assignee_id:
        logger.info(
            "Conversation already assigned",
            extra={
                "event": "bot_skip",
                "payload": {"reason": "assigned", "assignee_id": assignee_id},
            },
        )
        return {"message": "Conversation is assigned to someone"}

    if data.get("event") != "message_created":
        logger.info(
            "Skipping event",
            extra={"event": "bot_skip", "payload": {"reason": "not_message_created"}},
        )
        return {"message": "Not a message creation event"}

    if data.get("message_type") != "incoming":
        logger.info(
            "Skipping event",
            extra={"event": "bot_skip", "payload": {"reason": "not_incoming"}},
        )
        return {"message": "Not an incoming message"}

    if "sender" not in data:
        logger.warning(
            "Incoming payload missing sender",
            extra={"event": "bot_skip", "payload": {"reason": "no_sender"}},
        )
        return {"message": "No sender detected"}

    account_id = int(data["account"]["id"])
    conversation_id = data["conversation"]["id"]
    user_id = str(data["sender"]["id"])
    text = data.get("content", "") or ""

    cfg = await get_params_by_omnichannel_id(account_id)
    logger.info(
        "Configuration lookup complete",
        extra={
            "event": "tenant_config_lookup",
            "payload": {"account_id": account_id, "found": bool(cfg)},
        },
    )

    if not cfg:
        logger.error(
            "No tenant configuration found",
            extra={
                "event": "tenant_config_missing",
                "payload": {"account_id": account_id},
            },
        )
        return {"message": "No tenant configuration found for omnichannel id"}

    tenant_id = int(cfg.get("id", account_id))
    llm_params = cfg.get("llm_params") or {}
    omnichannel_params = cfg.get("omnichannel") or {}
    bot_usage_today = None
    bot_usage_month = None
    monthly_usage = None
    monthly_limit = None
    monthly_limit_raw = llm_params.get("monthly_llm_request_limit")
    chatwoot_api_url = omnichannel_params.get("chatwoot_api_url")
    chatwoot_bot_access_token = omnichannel_params.get("chatwoot_bot_access_token")

    if not chatwoot_api_url:
        logger.error(
            "Chatwoot API URL missing",
            extra={
                "event": "chatwoot_config_error",
                "payload": {"tenant_id": tenant_id, "account_id": account_id},
            },
        )
        return {"message": "Chatwoot API URL not configured"}

    if not chatwoot_bot_access_token:
        logger.error(
            "Chatwoot bot access token missing",
            extra={
                "event": "chatwoot_config_error",
                "payload": {"tenant_id": tenant_id, "account_id": account_id},
            },
        )
        return {"message": "Chatwoot access token not configured"}

    if monthly_limit_raw is not None:
        try:
            monthly_limit = int(monthly_limit_raw)
        except (TypeError, ValueError):
            monthly_limit = None
            logger.warning(
                "Invalid monthly limit configured",
                extra={
                    "event": "bot_limit_invalid",
                    "payload": {
                        "tenant_id": tenant_id,
                        "raw_value": monthly_limit_raw,
                    },
                },
            )

    if monthly_limit is not None and monthly_limit > 0:
        today = date.today()
        start_of_month = today.replace(day=1)
        try:
            monthly_usage = await get_bot_request_total(tenant_id, start_of_month, today)
            bot_usage_month = monthly_usage
            logger.info(
                "Monthly usage fetched",
                extra={
                    "event": "bot_usage_month",
                    "payload": {
                        "tenant_id": tenant_id,
                        "usage": monthly_usage,
                        "limit": monthly_limit,
                    },
                },
            )
        except Exception as exc:
            monthly_usage = None
            bot_usage_month = None
            logger.exception(
                "Failed to fetch monthly usage",
                extra={"event": "bot_usage_error", "payload": {"tenant_id": tenant_id}},
            )
        else:
            if monthly_usage >= monthly_limit:
                limit_message = llm_params.get(
                    "monthly_llm_limit_reached_reply",
                    "We have reached the automated response limit for this month. "
                    "A human teammate will take it from here.",
                )
                async with httpx.AsyncClient() as client:
                    await send_message(
                        client=client,
                        api_url=chatwoot_api_url,
                        access_token=chatwoot_bot_access_token,
                        account_id=account_id,
                        conversation_id=conversation_id,
                        content=limit_message,
                        private=False,
                    )
                return {
                    "message": "Monthly limit reached",
                    "bot_requests_month": monthly_usage,
                    "monthly_limit": monthly_limit,
                }

    try:
        bot_usage_today = await increment_bot_request_count(tenant_id)
        logger.info(
            "Bot usage incremented",
            extra={
                "event": "bot_usage_today",
                "payload": {"tenant_id": tenant_id, "count": bot_usage_today},
            },
        )
        if bot_usage_month is not None:
            bot_usage_month = bot_usage_month + 1
    except Exception as exc:
        logger.exception(
            "Failed to record bot usage",
            extra={"event": "bot_usage_error", "payload": {"tenant_id": tenant_id}},
        )

    handoff_public_reply = llm_params.get("handoff_public_reply")
    handoff_private_note = llm_params.get("handoff_private_note" )
    handoff_priority = llm_params.get("handoff_priority")

    state = SESSIONS.get(user_id) or initial_state()
    logger.info(
        "Handling user input",
        extra={
            "event": "bot_handle_input",
            "payload": {"tenant_id": tenant_id, "user_id": user_id},
        },
    )
    state, reply, status = await handle_input(
        state,
        text,
        tenant_id=cfg.get("id", account_id),
        runtime_config=cfg,
    )
    SESSIONS[user_id] = state

    async with httpx.AsyncClient() as client:
        if reply == "human_agent":
            await perform_handoff(
                client=client,
                account_id=account_id,
                conversation_id=conversation_id,
                api_url=chatwoot_api_url,
                access_token=chatwoot_bot_access_token,
                public_reply=handoff_public_reply,
                private_note=handoff_private_note,
                priority=handoff_priority,
            )
            return {"message": "Routing to human agent"}

        await send_message(
            client=client,
            api_url=chatwoot_api_url,
            access_token=chatwoot_bot_access_token,
            account_id=account_id,
            conversation_id=conversation_id,
            content=reply,
            private=False,
        )

    response = {"message": "VD Bot processed"}
    if bot_usage_today is not None:
        response["bot_requests_today"] = bot_usage_today
    if bot_usage_month is not None:
        response["bot_requests_month"] = bot_usage_month
    if monthly_limit is not None:
        response["monthly_limit"] = monthly_limit
    return response


__all__ = ["process_bot_request"]
