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

logger = logging.getLogger(__name__)

# Single instance of embedding model
_embed_model = None

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

def ingest_document(tenant_id: UUID, filename: str, content: str):
    """
    Parses, chunks, embeds, and inserts a document into the database.
    This should be run in a background task.
    """
    logger.info(f"Ingesting document {filename} for tenant {tenant_id}")

    # 1. Create LlamaIndex Document
    doc = Document(text=content, metadata={"filename": filename, "tenant_id": str(tenant_id)})

    # 2. Chunking
    splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=20)
    nodes = splitter.get_nodes_from_documents([doc])

    logger.info(f"Split into {len(nodes)} chunks")

    # 3. Embedding
    embed_model = get_embed_model()
    # Get embeddings for all nodes
    texts = [node.get_content() for node in nodes]

    try:
        # Note: Custom class relies on manual iteration for now if batch not supported well in custom wrapper
        # But our custom implementation iterates internally, so we just call it.
        embeddings = embed_model.get_text_embedding_batch(texts)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return # Stop ingestion if embedding fails

    # 4. Insert into DB
    with get_db() as conn:
        with conn.cursor() as cur:
            for node, embedding in zip(nodes, embeddings):
                # We store the chunk content (node.text) and vector
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
    use_rerank: bool = False
) -> List[Dict[str, Any]]:
    """
    Performs a hybrid search (currently vector similarity) for a query.
    Supports Query Expansion (HyDE) and Reranking.
    """
    # 1. Query Expansion (HyDE)
    search_query = query
    if use_hyde:
        logger.info("Using HyDE expansion")
        search_query = generate_hypothetical_answer(query)

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
        logger.info("Reranking results")
        # We rerank against the ORIGINAL query, not the HyDE query
        results = rerank_documents(query, results, top_k=limit)

    return results

# LLM Instance
_llm = None

def get_llm():
    global _llm
    if _llm is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "models/gemini-1.5-flash")
        _llm = Gemini(model=model_name, api_key=api_key)
    return _llm

def generate_answer(
    tenant_id: UUID,
    query: str,
    use_hyde: bool = False,
    use_rerank: bool = False
) -> str:
    """
    Retrieves context and generates an answer using the LLM.
    """
    logger.info(f"Generating answer for query: '{query}' | HyDE={use_hyde} | Rerank={use_rerank}")

    # 1. Retrieve Context
    results = search_documents(
        tenant_id,
        query,
        use_hyde=use_hyde,
        use_rerank=use_rerank
    )

    if not results:
        return "I could not find any relevant information in the documents."

    context_str = "\n\n".join([f"Source: {r['filename']}\n{r['content']}" for r in results])

    # 2. Prompt
    prompt = (
        "You are a helpful assistant for a RAG system.\n"
        "Use the following pieces of retrieved context to answer the user's question.\n"
        "If the answer is not in the context, say you don't know.\n\n"
        f"Context:\n{context_str}\n\n"
        f"Question: {query}\n\n"
        "Answer:"
    )

    # 3. Generate
    try:
        llm = get_llm()
        response = llm.complete(prompt)
        return response.text
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return "Sorry, I encountered an error generating the answer."
