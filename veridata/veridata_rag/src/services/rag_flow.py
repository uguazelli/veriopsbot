import os
import logging
from typing import List, Dict, Any, Optional
from uuid import UUID

from src.config.config import get_global_setting
from src.config.logging import log_start, log_success, log_error, log_llm, log_skip, log_external_call
from src.storage.repository import search_documents_hybrid
from src.services.embeddings import CustomGeminiEmbedding
from src.services.hyde import generate_hypothetical_answer
from src.services.rerank import rerank_documents
from src.services.llm_factory import get_llm
from src.services.memory import add_message, get_chat_history
from src.storage.repository import get_tenant_languages
from src.utils.prompts import (
    CONTEXTUALIZE_PROMPT_TEMPLATE
)

logger = logging.getLogger(__name__)

# Single instance of embedding model
_embed_model = None

def get_embed_model():
    global _embed_model
    if _embed_model is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY not set.")
        logger.info("Using Google Gemini Embeddings (models/text-embedding-004)")
        _embed_model = CustomGeminiEmbedding(
            model_name="models/text-embedding-004",
            api_key=api_key
        )
    return _embed_model

# ==================================================================================
# FLOW HELPER: CONTEXTUALIZE
# Rewrites the user query to include context from previous messages.
# Example: "How much is it?" -> "How much is the Standard Plan?"
# ==================================================================================
def contextualize_query(query: str, history: List[Dict[str, str]], provider: str = None) -> str:
    if not history:
        return query

    history_str = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])

    try:
        llm = get_llm(step="contextualization", provider=provider)
        prompt = CONTEXTUALIZE_PROMPT_TEMPLATE.format(history_str=history_str, query=query)
        response = llm.complete(prompt)
        rewritten = response.text.strip()
        logger.info(f"Contextualized query: '{query}' -> '{rewritten}'")
        return rewritten
    except Exception as e:
        logger.error(f"Contextualization failed: {e}")
        return query

# ==================================================================================
# RETRIEVAL ENGINE
# 1. HyDE (Optional): Hallucinate an answer to search for semantic concepts.
# 2. Embedding: Vectorize the query.
# 3. Search: Hybrid (Keyword + Semantic) search via Postgres.
# 4. Rerank (Optional): Use a cross-encoder to re-score results.
# ==================================================================================
async def search_documents(
    tenant_id: UUID,
    query: str,
    limit: int = 5,
    use_hyde: bool = False,
    use_rerank: bool = False,
    provider: str = "gemini"
) -> List[Dict[str, Any]]:
    search_query = query
    if use_hyde:
        logger.info(f"🔍 Opt 1 (Accuracy): Using HyDE expansion with {provider}")
        search_query = generate_hypothetical_answer(query, provider=provider)

    # 2. Embed Query
    embed_model = get_embed_model()
    try:
        query_embedding = embed_model.get_query_embedding(search_query)
    except Exception as e:
        logger.error(f"Query embedding failed: {e}")
        return []

    # 3. Retrieve Candidates (Delegated to Repository)
    # If using rerank, we fetch more candidates (e.g., 4x the limit) to rerank down
    candidate_limit = limit * 4 if use_rerank else limit

    logger.info(f"🔍 Opt 2 (Accuracy): Performing Hybrid Search (Vector + FTS) with RRF (Limit: {candidate_limit})")

    results = await search_documents_hybrid(tenant_id, query_embedding, query, candidate_limit)

    # 4. Reranking
    if use_rerank and results:
        logger.info(f"Reranking results with {provider}")
        # We rerank against the ORIGINAL query, not the HyDE query
        results = rerank_documents(query, results, top_k=limit, provider=provider)

    return results

# --- Flow Helpers ---

def resolve_config(use_hyde: Optional[bool], use_rerank: Optional[bool]) -> tuple[bool, bool]:
    if use_hyde is None:
        use_hyde = get_global_setting("use_hyde", False)
    if use_rerank is None:
        use_rerank = get_global_setting("use_rerank", False)
    return use_hyde, use_rerank

async def get_language_instruction(tenant_id: UUID) -> str:
    pref_langs = await get_tenant_languages(tenant_id)
    lang_instruction = ""
    if pref_langs:
        lang_instruction = f"Preferred Languages: {pref_langs}\n(Prioritize these if the user's language is ambiguous, but always match the user's input language)."
    logger.info(f"Tenant Preferences [{tenant_id}]: '{pref_langs}'")
    return lang_instruction

async def prepare_query_context(
    session_id: Optional[UUID],
    query: str,
    provider: Optional[str]
) -> tuple[str, List[Dict]]:
    search_query = query
    history = []
    if session_id:
        history = await get_chat_history(session_id, limit=5)
        if history:
            search_query = contextualize_query(query, history, provider)
    return search_query, history

# ==================================================================================
# FLOW HELPER: INTENT CLASSIFICATION
# Decides if we need RAG (Knowledge) or just Small Talk.
# Also routes complex queries (>7) to stronger models.
# ==================================================================================
def determine_intent(complexity_score: int, pricing_intent: bool) -> tuple[bool, str]:
    # Returns (requires_rag, gen_step)
    complexity = 5 if complexity_score is None else complexity_score

    requires_rag = True
    if complexity < 2 and not pricing_intent:
        requires_rag = False

    if pricing_intent:
        logger.info("🎯 Pricing intent detected.")

    gen_step = "generation"
    if complexity >= 7:
        logger.info(f"🧠 Opt 3 (Routing): Complexity {complexity} >= 7. Routing to High-Power model.")
        gen_step = "complex_reasoning"
    else:
        logger.info(f"⚡ Opt 3 (Routing): Complexity {complexity} < 7. Routing to Fast/Cheap model.")
        gen_step = "generation"

    return requires_rag, gen_step

# ==================================================================================
# FLOW HELPER: RETRIEVE CONTEXT
# Aggregates data from:
# 1. Live Data (Google Sheets/External API - passed as external_context)
# 2. Vector Store (search_documents)
# ==================================================================================
async def retrieve_context(
    tenant_id: UUID,
    search_query: str,
    external_context: Optional[str],
    use_hyde: bool,
    use_rerank: bool,
    provider: Optional[str],
    lang_instruction: str
) -> tuple[str, str]:
    # 1. External (Live) Data
    live_data = ""
    updated_lang_instruction = lang_instruction
    if external_context:
        logger.info("📊 Opt 1 (Live Data): Injecting external context provided by Bot.")
        updated_lang_instruction += "\nIMPORTANT: Use the [LIVE PRICING & PRODUCT DATA] section for any mention of products or costs. Trust it over other data. Be flexible with names (e.g., 'consultoria' matches 'Consulting Hour')."
        live_data = external_context

    # 2. Database (RAG) Data
    doc_context = ""
    results = await search_documents(
        tenant_id,
        search_query,
        use_hyde=use_hyde,
        use_rerank=use_rerank,
        provider=provider
    )
    if results:
        doc_context = "\n\n".join([f"Source: {r['filename']}\n{r['content']}" for r in results])

    # 3. Combine
    context_str = ""
    if live_data:
        context_str += live_data
    if doc_context:
        context_str += "\n" + doc_context
    if not context_str:
        context_str = "No relevant documents or live data found."

    return context_str, updated_lang_instruction

def generate_llm_response(
    prompt_template: str,
    template_args: Dict[str, Any],
    gen_step: str,
    provider: Optional[str]
) -> str:
    """Generic function to format a prompt and generate a response from the LLM."""
    try:
        prompt = prompt_template.format(**template_args)
        llm = get_llm(step=gen_step, provider=provider)
        response = llm.complete(prompt)
        return response.text
    except Exception as e:
        log_error(logger, f"LLM generation failed: {e}")
        return "Sorry, I encountered an error generating the answer."

async def save_interaction(session_id: Optional[UUID], query: str, answer: str):
    if session_id:
        try:
            await add_message(session_id, "user", query)
            await add_message(session_id, "ai", answer)
        except Exception as e:
            logger.error(f"Failed to save message history: {e}")
