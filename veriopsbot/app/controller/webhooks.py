"""Webhook controller functions."""

import logging

import requests

logger = logging.getLogger("veriops.webhooks")


def process_chatwoot_webhook(payload: dict):
    logger.info(
        "Chatwoot webhook payload received",
        extra={
            "event": "chatwoot_webhook",
            "payload": {
                "event": payload.get("event"),
                "conversation_id": payload.get("conversation_id"),
            },
        },
    )

    if not payload.get("event", "").startswith("contact_"):
        return {"message": "Not a contact event"}
    if not payload.get("phone_number") and not payload.get("email"):
        return {"message": "No phone number or email detected"}

    n8n = requests.post("http://host.docker.internal:5678/webhook/chatwoot", json=payload).json()
    n8ntest = requests.post("http://host.docker.internal:5678/webhook-test/chatwoot", json=payload).json()
    logger.info(
        "Chatwoot webhook forwarded",
        extra={
            "event": "chatwoot_webhook_forwarded",
            "payload": {"n8n": n8n, "n8n_test": n8ntest},
        },
    )
    return {"message": "Chatwoot webhook processed"}


def process_twenty_webhook(payload: dict):
    logger.info(
        "Twenty webhook received",
        extra={
            "event": "twenty_webhook",
            "payload": {"record_id": payload.get("id"), "type": payload.get("type")},
        },
    )

    if payload.get("record", {}).get("deletedAt"):
        logger.info(
            "Deletion detected, skipping n8n call",
            extra={"event": "twenty_webhook_skip", "payload": {"record_id": payload.get("id")}},
        )
        return {"message": "Deletion detected, skipping n8n call."}

    n8n = requests.post("http://host.docker.internal:5678/webhook/twenty", json=payload).json()
    n8ntest = requests.post("http://host.docker.internal:5678/webhook-test/twenty", json=payload).json()
    logger.info(
        "Twenty webhook forwarded",
        extra={
            "event": "twenty_webhook_forwarded",
            "payload": {"n8n": n8n, "n8n_test": n8ntest},
        },
    )
    return {"message": "Twenty webhook processed"}


__all__ = ["process_chatwoot_webhook", "process_twenty_webhook"]
