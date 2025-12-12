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
from src.memory import add_message, get_chat_history

logger = logging.getLogger(__name__)

# Single instance of embedding model
_embed_model = None

# ... existing imports ...

CONTEXTUALIZE_PROMPT_TEMPLATE = (
    "Given a chat history and the latest user question which might reference context in the chat history, "
    "formulate a standalone question which can be understood without the chat history. "
    "Do NOT answer the question, just reformulate it if needed and otherwise return it as is.\n\n"
    "Chat History:\n{history_str}\n\n"
    "Latest Question: {query}\n\n"
    "Standalone Question:"
)

INTENT_PROMPT_TEMPLATE = (
    "You are a router. Analyze the user's query and decide on two things:\n"
    "1. Does it require looking up external documents? (RAG)\n"
    "2. Does the user explicitly ask to speak to a human agent? (HUMAN)\n\n"
    "Rules for RAG:\n"
    "1. Greetings, thanks, or personal questions -> RAG = FALSE\n"
    "2. Questions about entities, products, policies, facts -> RAG = TRUE\n"
    "3. Ambiguous questions -> RAG = TRUE\n"
    "4. Unsure -> RAG = TRUE\n\n"
    "Rules for HUMAN:\n"
    "1. User says 'talk to human', 'real person', 'support agent', 'manager' -> HUMAN = TRUE\n"
    "2. Otherwise -> HUMAN = FALSE\n\n"
    "Return JSON with keys 'requires_rag' (bool) and 'requires_human' (bool).\n\n"
    "Query: {query}\n\n"
    "JSON Output:"
)

def analyze_intent(query: str, provider: str = "gemini") -> Dict[str, bool]:
    """
    Uses LLM to decide if RAG is needed and if human handoff is requested.
    """
    try:
        # Use a fast model for routing if possible
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
    """
    Rewrites the user query to be standalone based on chat history.
    """
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

# ... existing search_documents ...

def generate_answer(
    tenant_id: UUID,
    query: str,
    use_hyde: bool = False,
    use_rerank: bool = False,
    provider: str = "gemini",
    session_id: Optional[UUID] = None
) -> tuple[str, bool]:
    """
    Retrieves context and generates an answer using the requested LLM provider.
    Supports Conversational Memory and Intent Classification.
    """
    logger.info(f"Generating answer for query: '{query}' | Session={session_id} | Provider={provider}")

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

    results = []
    answer = ""

    # If human handoff is requested, short-circuit
    if requires_human:
        logger.info("Human handoff requested.")
        prompt = (
            "You are a helpful assistant.\n"
            "The user explicitly asked to speak to a human agent.\n"
            "Generate a polite response confirming you will transfer them to a human agent.\n"
            "IMPORTANT: Expected output must be in the SAME language as the user's message.\n"
            f"User Message: {search_query}\n"
            "Response:"
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
        prompt = (
            "You are a helpful assistant for a RAG system.\n"
            "Use the following pieces of retrieved context AND the chat history to answer the user's question.\n"
            "IMPORTANT: Always answer in the same language as the user's question.\n"
            "Priority:\n"
            "1. Use the retrieved context for factual information about the documents.\n"
            "2. Use the chat history for conversational context (e.g., user's name, previous topics).\n"
            "If the answer is not in the context or history, say you don't know.\n\n"
            f"Chat History:\n{history_str}\n\n"
            f"Retrieved Context:\n{context_str}\n\n"
            f"Question: {search_query}\n\n"
            "Answer:"
        )

        # 4. Generate
        try:
            llm = get_llm(provider)
            response = llm.complete(prompt)
            answer = response.text
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            answer = "Sorry, I encountered an error generating the answer."
    else:
        # 4. Small Talk / Direct Generation
        logger.info("Small talk detected. Bypassing RAG.")
        prompt = (
            "You are a helpful assistant.\n"
            "Respond to the following user message nicely and concisely.\n"
            "IMPORTANT: Always answer in the same language as the user's message.\n"
            "Use the chat history to maintain conversation context (e.g. remember names).\n"
            "Do NOT hallucinate information about documents you don't see.\n"
            f"Chat History:\n{history_str}\n\n"
            f"Message: {search_query}\n\n"
            "Response:"
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
    """
    Factory to get the Gemini embedding model.
    """
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

# ... existing imports ...

def ingest_document(tenant_id: UUID, filename: str, content: str = None, file_bytes: bytes = None):
    """
    Parses, chunks, embeds, and inserts a document into the database.
    Supports text files (content passed) and images (file_bytes passed).
    """
    logger.info(f"Ingesting document {filename} for tenant {tenant_id}")

    # 0. Handle Images (Multimodal)
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
    """
    Performs a hybrid search (currently vector similarity) for a query.
    Supports Query Expansion (HyDE) and Reranking.
    """
    # 1. Query Expansion (HyDE)
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


