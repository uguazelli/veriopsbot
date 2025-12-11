import os
import logging
import json
from typing import List, Dict, Any
from src.llm_factory import get_llm

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

def rerank_documents(query: str, documents: List[Dict[str, Any]], top_k: int = 5, provider: str = "gemini") -> List[Dict[str, Any]]:
    """
    Reranks a list of documents based on semantic relevance to the query using an LLM.
    Returns the top K documents.
    """
    if not documents:
        return []

    logger.info(f"Reranking {len(documents)} documents for query: {query} using {provider}")
    llm = get_llm(provider)
    scored_docs = []

    # Optimization: For better performance, we could batch this or use a CrossEncoder model.
    # For simplicity, we iterate.

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
