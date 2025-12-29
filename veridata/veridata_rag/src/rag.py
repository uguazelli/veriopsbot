import os
import logging
from typing import List, Dict, Any, Optional
from uuid import UUID

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from llama_index.llms.gemini import Gemini

from src.db import get_db
from src.embeddings import CustomGeminiEmbedding
from src.hyde import generate_hypothetical_answer
from src.rerank import rerank_documents
from src.llm_factory import get_llm
from src.memory import add_message, get_chat_history, get_full_chat_history
from src.logging import log_start, log_success, log_error, log_llm, log_skip, log_external_call
from src.prompts import (
    SUMMARY_PROMPT_TEMPLATE,
    CONTEXTUALIZE_PROMPT_TEMPLATE,
    INTENT_PROMPT_TEMPLATE,
    HANDOFF_PROMPT_TEMPLATE,
    RAG_ANSWER_PROMPT_TEMPLATE,
    SMALL_TALK_PROMPT_TEMPLATE
)

logger = logging.getLogger(__name__)

# Single instance of embedding model
_embed_model = None



def summarize_conversation(session_id: UUID, provider: str = "gemini") -> Dict[str, Any]:
    history = get_full_chat_history(session_id)
    if not history:
        logger.warning(f"No history found for session {session_id}")
        return {
            "purchase_intent": "None",
            "urgency_level": "Low",
            "sentiment_score": "Neutral",
            "detected_budget": None,
            "ai_summary": "No history available to summarize.",
            "contact_info": {},
            "client_description": None
        }

    history_str = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])

    try:
        llm = get_llm(provider)
        prompt = SUMMARY_PROMPT_TEMPLATE.format(history_str=history_str)
        response = llm.complete(prompt)
        text = response.text.replace('```json', '').replace('```', '').strip()
        log_llm(logger, f"Summarization response: {text}")

        import json
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import ast
            logger.warning("JSON decode failed, trying literal_eval")
            return ast.literal_eval(text)

    except Exception as e:
        log_error(logger, f"Summarization failed: {e}")
        # Return fallback object that matches the Pydantic schema
        return {
            "purchase_intent": "None",
            "urgency_level": "Low",
            "sentiment_score": "Neutral",
            "detected_budget": None,
            "ai_summary": f"Summarization failed due to error: {str(e)}",
            "contact_info": {},
            "client_description": None
        }


def analyze_intent(query: str, provider: str = "gemini") -> Dict[str, bool]:
    try:
        llm = get_llm(provider)
        prompt = INTENT_PROMPT_TEMPLATE.format(query=query)
        response = llm.complete(prompt)
        text = response.text.replace('```json', '').replace('```', '').strip()
        import json
        data = json.loads(text)
        requires_rag = data.get('requires_rag', True)
        requires_human = data.get('requires_human', False)
        logger.info(f"Intent Classification: '{query}' -> RAG: {requires_rag}, Human: {requires_human}")
        return {"requires_rag": requires_rag, "requires_human": requires_human}
    except Exception as e:
        logger.warning(f"Intent classification failed, defaulting to RAG=True, Human=False: {e}")
        return {"requires_rag": True, "requires_human": False}

def contextualize_query(query: str, history: List[Dict[str, str]], provider: str = "gemini") -> str:
    if not history:
        return query

    history_str = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])

    try:
        llm = get_llm(provider)
        prompt = CONTEXTUALIZE_PROMPT_TEMPLATE.format(history_str=history_str, query=query)
        response = llm.complete(prompt)
        rewritten = response.text.strip()
        logger.info(f"Contextualized query: '{query}' -> '{rewritten}'")
        return rewritten
    except Exception as e:
        logger.error(f"Contextualization failed: {e}")
        return query

# Helper
def get_tenant_languages(tenant_id: UUID) -> str:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT preferred_languages FROM tenants WHERE id = %s", (tenant_id,))
                res = cur.fetchone()
                return res[0] if res and res[0] else None
    except Exception as e:
        logger.error(f"Failed to fetch tenant languages: {e}")
        return None

def generate_answer(
    tenant_id: UUID,
    query: str,
    use_hyde: bool = False,
    use_rerank: bool = False,
    provider: str = "gemini",
    session_id: Optional[UUID] = None
) -> tuple[str, bool]:
    log_start(logger, f"Generating answer for query: '{query}' | Session={session_id} | Provider={provider}")

    # Fetch Tenant Preferences
    pref_langs = get_tenant_languages(tenant_id)
    lang_instruction = ""
    if pref_langs:
        lang_instruction = f"Preferred Languages: {pref_langs}\n(Prioritize these if the user's language is ambiguous, but always match the user's input language)."

    logger.info(f"Tenant Preferences [{tenant_id}]: '{pref_langs}'")
    # logger.info(f"Language Instruction: '{lang_instruction}'")

    # 1. Handle Memory (Contextualization)
    search_query = query
    history = []
    if session_id:
        history = get_chat_history(session_id, limit=5)
        if history:
            search_query = contextualize_query(query, history, provider)

    # 2. Intent Classification (Small Talk vs RAG vs Human)
    intent = analyze_intent(search_query, provider)
    requires_rag = intent["requires_rag"]
    requires_human = intent["requires_human"]

    # Force human handoff if the intent classifier is unsure but query seems urgent?
    # (Just sticking to the classifier for now)

    results = []
    answer = ""

    # If human handoff is requested, short-circuit
    if requires_human:
        logger.info("Human handoff requested.")
        prompt = HANDOFF_PROMPT_TEMPLATE.format(
            lang_instruction=lang_instruction,
            search_query=search_query
        )
        try:
            llm = get_llm(provider)
            response = llm.complete(prompt)
            return response.text.strip(), True
        except Exception as e:
            logger.error(f"LLM generation for handoff failed: {e}")
            return "I will transfer you to a human agent.", True

    # Format history for EITHER prompt
    history_str = ""
    if history:
        history_str = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])

    if requires_rag:
        # 3. Retrieve Context (ONLY if needed)
        results = search_documents(
            tenant_id,
            search_query,
            use_hyde=use_hyde,
            use_rerank=use_rerank,
            provider=provider
        )

        if not results:
            # If no docs found, try answering from history alone if possible, or fail gracefully
            context_str = "No relevant documents found."
        else:
            context_str = "\n\n".join([f"Source: {r['filename']}\n{r['content']}" for r in results])

        # 3. Prompt (RAG)
        # 3. Prompt (RAG)
        prompt = RAG_ANSWER_PROMPT_TEMPLATE.format(
            lang_instruction=lang_instruction,
            history_str=history_str,
            context_str=context_str,
            search_query=search_query
        )

        # 4. Generate
        try:
            llm = get_llm(provider)
            response = llm.complete(prompt)
            answer = response.text
        except Exception as e:
            log_error(logger, f"LLM generation failed: {e}")
            answer = "Sorry, I encountered an error generating the answer."
    else:
        # 4. Small Talk / Direct Generation
        log_skip(logger, "Small talk detected. Bypassing RAG.")
        prompt = SMALL_TALK_PROMPT_TEMPLATE.format(
            lang_instruction=lang_instruction,
            history_str=history_str,
            search_query=search_query
        )
        try:
            llm = get_llm(provider)
            response = llm.complete(prompt)
            answer = response.text
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            answer = "Sorry, I encountered an error generating the answer."

    # 5. Save Logic (if session active)
    if session_id:
        try:
            add_message(session_id, "user", query) # Save ORIGINAL query
            add_message(session_id, "ai", answer)
        except Exception as e:
            logger.error(f"Failed to save message history: {e}")

    return answer, False

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

from src.vlm import describe_image

def ingest_document(tenant_id: UUID, filename: str, content: str = None, file_bytes: bytes = None):
    logger.info(f"Ingesting document {filename} for tenant {tenant_id}")

    is_image = filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))

    if is_image:
        if not file_bytes:
            logger.error("Image ingestion requires file_bytes")
            return
        logger.info("Processing image with VLM...")
        # Overwrite content with the image description
        content = describe_image(file_bytes, filename)
        # We can prepend a tag so we know it's an image description
        content = f"[IMAGE DESCRIPTION for {filename}]\n{content}"

    if not content:
        logger.warning(f"No content to ingest for {filename}")
        return

    # 1. Create LlamaIndex Document
    doc = Document(
        text=content,
        metadata={
            "filename": filename,
            "tenant_id": str(tenant_id),
            "original_type": "image" if is_image else "text"
        }
    )

    # 2. Chunking
    splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=20)
    nodes = splitter.get_nodes_from_documents([doc])

    logger.info(f"Split into {len(nodes)} chunks")

    # 3. Embedding
    embed_model = get_embed_model()
    texts = [node.get_content() for node in nodes]

    try:
        embeddings = embed_model.get_text_embedding_batch(texts)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return

    # 4. Insert into DB
    with get_db() as conn:
        with conn.cursor() as cur:
            for node, embedding in zip(nodes, embeddings):
                cur.execute(
                    """
                    INSERT INTO documents (tenant_id, filename, content, embedding)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (tenant_id, filename, node.get_content(), embedding)
                )
    logger.info(f"Successfully ingested {filename}")

def search_documents(
    tenant_id: UUID,
    query: str,
    limit: int = 5,
    use_hyde: bool = False,
    use_rerank: bool = False,
    provider: str = "gemini"
) -> List[Dict[str, Any]]:
    search_query = query
    if use_hyde:
        logger.info(f"Using HyDE expansion with {provider}")
        search_query = generate_hypothetical_answer(query, provider=provider)

    # 2. Embed Query
    embed_model = get_embed_model()
    try:
        query_embedding = embed_model.get_query_embedding(search_query)
    except Exception as e:
        logger.error(f"Query embedding failed: {e}")
        return []

    # 3. Retrieve Candidates
    # If using rerank, we fetch more candidates (e.g., 4x the limit) to rerank down
    candidate_limit = limit * 4 if use_rerank else limit

    results = []
    with get_db() as conn:
        with conn.cursor() as cur:
            # Vector search with Cosine Similarity (<=> operator)
            # Ordered by distance ASC (closest first)
            cur.execute(
                """
                SELECT id, filename, content, (embedding <=> %s::vector) as distance
                FROM documents
                WHERE tenant_id = %s
                ORDER BY distance ASC
                LIMIT %s
                """,
                (query_embedding, tenant_id, candidate_limit)
            )
            rows = cur.fetchall()

            for row in rows:
                results.append({
                    "id": str(row[0]),
                    "filename": row[1],
                    "content": row[2],
                    "distance": float(row[3])
                })

    # 4. Reranking
    if use_rerank and results:
        logger.info(f"Reranking results with {provider}")
        # We rerank against the ORIGINAL query, not the HyDE query
        results = rerank_documents(query, results, top_k=limit, provider=provider)

    return results


