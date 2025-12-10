import os
import logging
import json
from typing import List, Dict, Any
from llama_index.llms.gemini import Gemini

logger = logging.getLogger(__name__)

RERANK_PROMPT_TEMPLATE = (
    "You are a relevance ranking system. "
    "Check if the following document is relevant to the query. "
    "Assign a relevance score from 0 to 10. "
    "Return ONLY a JSON object with a single key 'score' (integer).\n\n"
    "Query: {query}\n"
    "Document: {content}\n\n"
    "JSON Output:"
)

_rerank_llm = None

def get_rerank_llm():
    global _rerank_llm
    if _rerank_llm is None:
        # Re-ranking needs a slightly smarter model if possible, but 1.5-flash is fast
        api_key = os.getenv("GOOGLE_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "models/gemini-1.5-flash")
        _rerank_llm = Gemini(model=model_name, api_key=api_key)
    return _rerank_llm

def rerank_documents(query: str, documents: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Reranks a list of documents based on semantic relevance to the query using an LLM.
    Returns the top K documents.
    """
    if not documents:
        return []

    logger.info(f"Reranking {len(documents)} documents for query: {query}")
    llm = get_rerank_llm()
    scored_docs = []

    # Optimization: For better performance, we could batch this or use a CrossEncoder model.
    # For simplicity and pure Gemini stack, we iterate.
    # Parallel execution would be better here, but requires async flow. Keeping it sequential-ish for MVP reliability.

    for doc in documents:
        try:
            # Truncate content for reranking to save cost/latency
            content_preview = doc['content'][:1000]
            prompt = RERANK_PROMPT_TEMPLATE.format(query=query, content=content_preview)

            response = llm.complete(prompt)
            # Try to parse JSON from response
            text = response.text.replace('```json', '').replace('```', '').strip()
            score_data = json.loads(text)
            score = score_data.get('score', 0)

            doc['rerank_score'] = score
            scored_docs.append(doc)

        except Exception as e:
            logger.warning(f"Reranking failed for doc {doc.get('id')}: {e}")
            doc['rerank_score'] = 0
            scored_docs.append(doc)

    # Sort by score DESC
    scored_docs.sort(key=lambda x: x['rerank_score'], reverse=True)

    # Return top K
    return scored_docs[:top_k]
