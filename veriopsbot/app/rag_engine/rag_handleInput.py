"""Intent classification for incoming user messages."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional, Tuple

from .rag_llm import chat_completion
from .rag_memory import MemoryState

Intent = Literal["smalltalk", "rag", "handoff"]

_LOGGER = logging.getLogger(__name__)


async def classify_user_message(
    llm: Optional[Any],
    memory: MemoryState,
    message: str,
) -> Tuple[Intent, Optional[str]]:
    """Ask the LLM to decide how to handle the incoming message."""
    if not llm:
        # Heuristic fallback when no model is configured.
        lowered = message.lower()
        if any(keyword in lowered for keyword in ("human", "agent", "representative")):
            return "handoff", "User requested a human agent."
        if any(greeting in lowered for greeting in ("hello", "hi", "hey")):
            return "smalltalk", None
        return "rag", None

    transcript = memory.transcript()
    system_prompt = (
        "You are an intent classifier for an AI support assistant. "
        "Classify the user's request into exactly one of these intents:\n"
        "- smalltalk: greetings, introductions, pleasantries, or casual conversation that does not need retrieval.\n"
        "- rag: the user is asking for information, troubleshooting, or knowledge lookup.\n"
        "- handoff: the user asks for a human or says the bot cannot help.\n"
        "Respond with JSON in the form {\"intent\": \"<smalltalk|rag|handoff>\"} and optionally include "
        "\"reason\" if it helps explain your choice."
    )

    user_prompt = (
        "Conversation so far:\n"
        f"{transcript or '(no history)'}\n\n"
        f"Incoming message: {message}\n"
        "Respond ONLY with JSON like {\"intent\": \"rag\"} and optional \"reason\"."
    )

    try:
        raw = await chat_completion(llm, user_prompt, system_prompt=system_prompt)
        data = json.loads(raw)
        _LOGGER.info(
            "LLM intent classification",
            extra={"event": "rag_intent_llm", "payload": data},
        )
        intent = data.get("intent", "rag").lower()
        if intent not in {"smalltalk", "rag", "handoff"}:
            intent = "rag"
        reason = data.get("reason")
        return intent, reason
    except Exception as exc:  # pragma: no cover - LLM failures are runtime concerns
        _LOGGER.warning("LLM intent classification failed, defaulting to RAG: %s", exc)
        return "rag", None
