import os
import logging
from llama_index.llms.gemini import Gemini

logger = logging.getLogger(__name__)

HYDE_PROMPT_TEMPLATE = (
    "Please write a short passage that answers the following question. "
    "Do not include any explanation, just the answer. "
    "It does not have to be true, just semantically relevant to the question.\n\n"
    "Question: {query}\n\n"
    "Passage:"
)

_hyde_llm = None

def get_hyde_llm():
    global _hyde_llm
    if _hyde_llm is None:
        # We use a fast model for HyDE (1.5-flash is perfect)
        api_key = os.getenv("GOOGLE_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "models/gemini-1.5-flash")
        _hyde_llm = Gemini(model=model_name, api_key=api_key)
    return _hyde_llm

def generate_hypothetical_answer(query: str) -> str:
    """
    Generates a hypothetical document/answer for the given query using HyDE (Hypothetical Document Embeddings).
    This helps in retrieving documents that are semantically similar to the answer rather than the question.
    """
    try:
        llm = get_hyde_llm()
        response = llm.complete(HYDE_PROMPT_TEMPLATE.format(query=query))
        hypothetical = response.text.strip()
        logger.info(f"HyDE generated: {hypothetical[:100]}...")
        return hypothetical
    except Exception as e:
        logger.error(f"HyDE generation failed: {e}")
        # Fallback to original query if HyDE fails
        return query
