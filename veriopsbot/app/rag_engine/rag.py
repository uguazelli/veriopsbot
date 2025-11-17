"""Orchestrates the RAG pipeline for chat interactions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import logging

from llama_index.core import Settings
from llama_index.core.schema import NodeWithScore

from .helpers import configure_llm_from_config, get_query_engine
from .rag_handleInput import classify_user_message
from .rag_llm import chat_completion
from .rag_memory import MemoryState


logger = logging.getLogger("veriops.rag")


def initial_state() -> MemoryState:
    return MemoryState()


async def handle_input(
    state: MemoryState,
    user_message: str,
    tenant_id: int,
    *,
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Tuple[MemoryState, str, str]:
    config = runtime_config or {}
    llm_params = configure_llm_from_config(config)

    if state.tenant_id is None:
        state.tenant_id = tenant_id

    llm = getattr(Settings, "llm", None)
    logger.info(
        "Starting intent classification",
        extra={"event": "rag_intent_start", "payload": {"tenant_id": tenant_id}},
    )
    intent, reason = await classify_user_message(llm, state, user_message)
    logger.info(
        "Intent classified",
        extra={
            "event": "rag_intent_result",
            "payload": {"intent": intent, "reason": reason},
        },
    )

    state.remember("user", user_message)

    if intent == "smalltalk":
        reply: str
        if llm:
            system_prompt = llm_params.get(
                "smalltalk_system_prompt",
                "You are a warm, professional assistant. Reply concisely in the same language as the user.",
            )
            user_prompt = (
                f"Conversation to date:\n{state.transcript() or '(no history)'}\n\n"
                f"Most recent user message:\n{user_message}"
            )
            try:
                reply = await chat_completion(llm, user_prompt, system_prompt=system_prompt)
            except Exception:
                reply = llm_params.get(
                    "smalltalk_reply",
                    "Hello! How can I assist you today?",
                )
        else:
            reply = llm_params.get(
                "smalltalk_reply",
                "Hello! How can I assist you today?",
            )
        state.remember("assistant", reply)
        return state, reply, "smalltalk"

    if intent == "handoff":
        return state, "human_agent", "handoff"

    query_engine = await get_query_engine(
        account_id=int(config.get("omnichannel_id", tenant_id)),
        tenant_id=state.tenant_id,
        runtime_config=config,
        llm_params=llm_params,
    )

    response = query_engine.query(user_message)
    retrieved_nodes = list(getattr(response, "source_nodes", []) or [])
    raw_answer = (getattr(response, "response", None) or str(response or "")).strip()

    logger.info(
        "RAG raw answer",
        extra={"event": "rag_raw_answer", "payload": {"answer": raw_answer}},
    )
    if retrieved_nodes:
        logger.info(
            "Retrieved nodes",
            extra={
                "event": "rag_nodes",
                "payload": {"count": len(retrieved_nodes)},
            },
        )
        for idx, node in enumerate(retrieved_nodes, start=1):
            try:
                snippet = node.node.get_content()
            except AttributeError:
                snippet = str(node)
            logger.debug(
                "Node %s score=%s snippet=%s",
                idx,
                getattr(node, "score", "n/a"),
                snippet[:200],
                extra={"event": "rag_node_detail"},
            )
    else:
        logger.info(
            "No retrieved nodes",
            extra={"event": "rag_nodes", "payload": {"count": 0}},
        )

    reply = await _compose_conversational_answer(
        llm=llm,
        memory=state,
        user_message=user_message,
        nodes=retrieved_nodes,
        llm_params=llm_params,
        raw_answer=raw_answer,
    )
    state.remember("assistant", reply)

    return state, reply, "rag"


async def _compose_conversational_answer(
    llm,
    memory: MemoryState,
    user_message: str,
    nodes: List[NodeWithScore],
    llm_params: Dict[str, Any],
    raw_answer: str,
) -> str:
    if llm is None:
        if raw_answer:
            return raw_answer
        if nodes:
            snippets = "\n\n".join(
                f"- {node.node.get_content()}" for node in nodes
            )
            return f"Aqui está o que encontrei:\n{snippets}"
        return "I couldn't find information related to that yet."

    conversation = memory.transcript() or "(no history)"
    knowledge = "\n\n".join(
        f"Source {idx + 1} (score={node.score:.2f}):\n{node.node.get_content()}"
        for idx, node in enumerate(nodes)
    ) or "No supporting documents were retrieved."

    system_prompt = llm_params.get(
        "rag_system_prompt",
        "You are a knowledgeable support assistant. "
        "Use both the conversation history and the provided knowledge snippets to answer the user's latest message. "
        "If the conversation already contains the answer, rely on it. "
        "If the knowledge snippets are helpful, weave them into the reply naturally. "
        "If you do not know, say so politely.",
    )
    user_prompt = (
        f"Conversation history:\n{conversation}\n\n"
        f"Knowledge snippets:\n{knowledge}\n\n"
        f"Latest user message:\n{user_message}\n\n"
        "Compose a concise, helpful reply in the same language as the user."
    )

    try:
        reply = await chat_completion(llm, user_prompt, system_prompt=system_prompt)
    except Exception:
        reply = ""

    if reply.strip():
        return reply.strip()

    if raw_answer:
        return raw_answer

    if nodes:
        fallback = "\n\n".join(node.node.get_content() for node in nodes)
        return fallback or "I couldn't find information related to that yet."

    return "I couldn't find information related to that yet."
