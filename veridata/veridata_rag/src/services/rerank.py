import logging
import json
from typing import List, Dict, Any
from src.services.llm_factory import get_llm

logger = logging.getLogger(__name__)

from src.utils.prompts import RERANK_PROMPT_TEMPLATE


def rerank_documents(
    query: str, documents: List[Dict[str, Any]], top_k: int = 5, provider: str = None
) -> List[Dict[str, Any]]:
    if not documents:
        return []

    logger.info(
        f"Reranking {len(documents)} documents for query: {query} using step 'rag_search'"
    )
    llm = get_llm(step="rag_search", provider=provider)
    scored_docs = []

    for doc in documents:
        try:
            content_preview = doc["content"][:1000]
            prompt = RERANK_PROMPT_TEMPLATE.format(query=query, content=content_preview)

            response = llm.complete(prompt)
            text = response.text.replace("```json", "").replace("```", "").strip()
            score_data = json.loads(text)
            score = score_data.get("score", 0)

            doc["rerank_score"] = score
            scored_docs.append(doc)

        except Exception as e:
            logger.warning(f"Reranking failed for doc {doc.get('id')}: {e}")
            doc["rerank_score"] = 0
            scored_docs.append(doc)

    scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored_docs[:top_k]
