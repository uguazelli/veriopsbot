import os
import logging
from typing import Optional, Any
from llama_index.llms.gemini import Gemini
from llama_index.llms.openai import OpenAI

logger = logging.getLogger(__name__)

# Instances cache
_llm_instances = {}

def get_llm(provider: str = "gemini") -> Any:
    """
    Factory to get an LLM instance based on provider name.
    """
    provider = provider.lower()

    if provider in _llm_instances:
        return _llm_instances[provider]

    logger.info(f"Initializing LLM provider: {provider}")

    llm = None

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY not found. Fallback to Gemini.")
            return get_llm("gemini")

        # Default to gpt-4o as discussed with user, or allow env override
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o")
        llm = OpenAI(model=model_name, api_key=api_key)

    elif provider == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not set.")
        model_name = os.getenv("GEMINI_MODEL", "models/gemini-2.0-flash")
        llm = Gemini(model=model_name, api_key=api_key)

    else:
        logger.warning(f"Unknown provider '{provider}'. Defaulting to Gemini.")
        return get_llm("gemini")

    _llm_instances[provider] = llm
    return llm

def get_hyde_llm(provider: str = "gemini") -> Any:
    """
    Get a fast LLM for HyDE.
    Ideally simply uses the same provider but maybe a faster model variant if we were optimizing.
    For MVP, just reuse the main get_llm or default to Gemini Flash for speed?
    Let's respect the provider choice but stick to the factory defaults.
    """
    return get_llm(provider)

def get_rerank_llm(provider: str = "gemini") -> Any:
    return get_llm(provider)
