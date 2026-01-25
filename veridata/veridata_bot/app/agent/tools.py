from typing import Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from app.integrations.rag import RagClient
from app.integrations.sheets import fetch_google_sheet_data
import logging
import uuid
import json

logger = logging.getLogger(__name__)

@tool
async def search_knowledge_base(query: str, config: RunnableConfig) -> str:
    """
    Search the knowledge base (RAG) for information about the company, products, or services.
    Use this for any user question that requires factual information.
    """
    # 1. Extract Config from Runtime
    # The 'configurable' dict is passed via ainvoke(..., config={"configurable": {...}})
    configuration = config.get("configurable", {})
    rag_config = configuration.get("rag_config", {})

    if not rag_config:
        return "Error: RAG Configuration missing. Cannot search."

    # 2. Setup Client
    try:
        base_url = rag_config.get("base_url")
        api_key = rag_config.get("api_key", "")
        tenant_id = rag_config.get("tenant_id")

        # Session ID handling (Agent should ideally pass this, or we trust the state?)
        # For simplicity, we might look for 'rag_session_id' in configurable if provided,
        # otherwise let the RAG service create/handle it or stateless.
        # But RAG `query` expects session_id for history context if we want it.
        # For ReAct, the Agent holds the history in 'messages'.
        # RAG might benefit from knowing the session ID for logging/persistence side-effects.
        rag_session_id_str = configuration.get("rag_session_id")
        rag_session_id = None
        if rag_session_id_str:
            try:
                rag_session_id = uuid.UUID(rag_session_id_str)
            except:
                pass

        client = RagClient(base_url=base_url, api_key=api_key, tenant_id=tenant_id)

        # 3. Call RAG
        # We simplify the call. Agent handles history, so RAG might not need full context history
        # if the query is comprehensive, but ReAct queries are often short.
        # We pass 'complexity_score' defaults.
        response_data = await client.query(
            message=query,
            session_id=rag_session_id,
            complexity_score=5, # Default
            pricing_intent=False, # We have a separate tool for pricing
            use_hyde=False,
            use_rerank=True
        )

        return response_data.get("answer", "No info found.")

    except Exception as e:
        logger.error(f"RAG Tool Error: {e}")
        return "I'm having trouble connecting to the knowledge base."


@tool
async def lookup_pricing(query: str, config: RunnableConfig) -> str:
    """
    Fetch the product price list and rules from the official Google Sheet.
    Use this when the user asks about prices, costs, or product availability.
    Returns the RAW text data from the sheet. You must then interpret it to answer.
    """
    configuration = config.get("configurable", {})
    google_sheets_url = configuration.get("google_sheets_url")

    if not google_sheets_url:
        return "Error: No pricing sheet configured."

    try:
        data = await fetch_google_sheet_data(google_sheets_url)
        if not data:
            return "The pricing sheet is empty or could not be read."
        return f"PRICING DATA:\n{data}"
    except Exception as e:
        logger.error(f"Pricing Tool Error: {e}")
        return "Could not fetch pricing data."


@tool
def transfer_to_human() -> str:
    """
    Call this tool when the user explicitly asks to speak with a human or support agent,
    OR when you cannot resolve the user's issue after trying.
    """
    return "TRANSFERRED_TO_HUMAN"
