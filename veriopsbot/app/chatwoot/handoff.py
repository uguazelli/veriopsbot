from typing import Optional
import logging

import httpx

logger = logging.getLogger("veriops.chatwoot")

def _headers(access_token: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "api_access_token": access_token}


async def send_message( *, client: httpx.AsyncClient, api_url: str, access_token: str, account_id: int, conversation_id: int, content: Optional[str], private: bool,) -> None:
    if not content:
        return
    try:
        resp = await client.post(
            f"{api_url}/accounts/{account_id}/conversations/{conversation_id}/messages",
            headers=_headers(access_token),
            json={
                "content": content,
                "message_type": "outgoing",
                "private": private,
            },
        )
        if resp.status_code >= 300:
            logger.error(
                "Error posting message",
                extra={
                    "event": "chatwoot_send_message_error",
                    "payload": {
                        "status": resp.status_code,
                        "body": resp.text[:500],
                        "conversation_id": conversation_id,
                    },
                },
            )
    except httpx.HTTPError as exc:
        logger.exception(
            "HTTP error posting message",
            extra={
                "event": "chatwoot_send_message_error",
                "payload": {"conversation_id": conversation_id},
            },
        )


async def perform_handoff( *, client: httpx.AsyncClient, account_id: int, conversation_id: int, api_url: str, access_token: str, public_reply: Optional[str], private_note: Optional[str], priority: Optional[str],) -> None:
    logger.info(
        "Sending handoff reply",
        extra={
            "event": "handoff_start",
            "payload": {
                "account_id": account_id,
                "conversation_id": conversation_id,
            },
        },
    )
    await send_message(
        client=client,
        api_url=api_url,
        access_token=access_token,
        account_id=account_id,
        conversation_id=conversation_id,
        content=public_reply,
        private=False,
    )
    await send_message(
        client=client,
        api_url=api_url,
        access_token=access_token,
        account_id=account_id,
        conversation_id=conversation_id,
        content=private_note,
        private=True,
    )

    try:
        logger.info(
            "Updating priority to %s (account=%s conversation=%s)",
            priority,
            account_id,
            conversation_id,
            extra={"event": "handoff_priority"},
        )
        resp = await client.patch(
            f"{api_url}/accounts/{account_id}/conversations/{conversation_id}",
            headers=_headers(access_token),
            json={"priority": priority},
        )
        if resp.status_code >= 300:
            logger.error(
                "Error setting priority",
                extra={
                    "event": "handoff_priority_error",
                    "payload": {
                        "status": resp.status_code,
                        "body": resp.text[:500],
                        "conversation_id": conversation_id,
                    },
                },
            )
        else:
            logger.info(
                "Priority set to %s (account=%s conversation=%s)",
                priority,
                account_id,
                conversation_id,
                extra={"event": "handoff_priority_set"},
            )
    except httpx.HTTPError as exc:
        logger.exception(
            "HTTP error setting priority",
            extra={
                "event": "handoff_priority_error",
                "payload": {"conversation_id": conversation_id},
            },
        )
