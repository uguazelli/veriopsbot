import logging
from src.llm_factory import get_llm

logger = logging.getLogger(__name__)

from src.prompts import HYDE_PROMPT_TEMPLATE

def generate_hypothetical_answer(query: str, provider: str = "gemini") -> str:
    try:
        llm = get_llm(provider)
        response = llm.complete(HYDE_PROMPT_TEMPLATE.format(query=query))
        hypothetical = response.text.strip()
        logger.info(f"HyDE generated ({provider}): {hypothetical[:100]}...")
        return hypothetical
    except Exception as e:
        logger.error(f"HyDE generation failed: {e}")
        return query
