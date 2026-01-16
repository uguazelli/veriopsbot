import logging
from src.services.llm_factory import get_llm

logger = logging.getLogger(__name__)

from src.utils.prompts import HYDE_PROMPT_TEMPLATE


def generate_hypothetical_answer(query: str, provider: str = None) -> str:
    try:
        llm = get_llm(step="rag_search", provider=provider)
        response = llm.complete(HYDE_PROMPT_TEMPLATE.format(query=query))
        hypothetical = response.text.strip()
        logger.info(f"HyDE generated (rag_search): {hypothetical[:100]}...")
        return hypothetical
    except Exception as e:
        logger.error(f"HyDE generation failed: {e}")
        return query
