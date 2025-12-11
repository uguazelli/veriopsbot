import os
import logging
from src.llm_factory import get_llm

logger = logging.getLogger(__name__)

HYDE_PROMPT_TEMPLATE = (
    "Please write a short passage that answers the following question. "
    "Do not include any explanation, just the answer. "
    "It does not have to be true, just semantically relevant to the question.\n\n"
    "Question: {query}\n\n"
    "Passage:"
)

def generate_hypothetical_answer(query: str, provider: str = "gemini") -> str:
    """
    Generates a hypothetical document/answer for the given query.
    """
    try:
        llm = get_llm(provider)
        response = llm.complete(HYDE_PROMPT_TEMPLATE.format(query=query))
        hypothetical = response.text.strip()
        logger.info(f"HyDE generated ({provider}): {hypothetical[:100]}...")
        return hypothetical
    except Exception as e:
        logger.error(f"HyDE generation failed: {e}")
        return query
