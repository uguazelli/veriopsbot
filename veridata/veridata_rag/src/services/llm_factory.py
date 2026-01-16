import os
import logging
from typing import Any
from llama_index.llms.gemini import Gemini
from llama_index.llms.openai import OpenAI
from src.config.config import get_llm_settings

logger = logging.getLogger(__name__)

_llm_instances = {}


def get_llm(step: str = "generation", provider: str = None, model_name: str = None) -> Any:
    settings = {}
    if provider:
        settings = {"provider": provider.lower(), "model": None}
    else:
        settings = get_llm_settings(step)

    provider = settings.get("provider", "gemini").lower()

    # Priority: Passed ARG > Config/Env > Default
    configured_model = settings.get("model")
    final_model_name = model_name or configured_model

    instance_key = f"{provider}:{final_model_name}"

    if instance_key in _llm_instances:
        return _llm_instances[instance_key]

    logger.info(
        f"Initializing LLM for step '{step}' (Provider: {provider}, Model: {final_model_name})"
    )

    llm = None

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY not found. Fallback to Gemini.")
            return get_llm(step=step, provider="gemini", model_name=model_name)

        final_model_name = final_model_name or os.getenv("OPENAI_MODEL", "gpt-4o")
        llm = OpenAI(model=final_model_name, api_key=api_key)

    elif provider == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not set.")
        final_model_name = final_model_name or os.getenv("GEMINI_MODEL", "models/gemini-2.0-flash")
        llm = Gemini(model=final_model_name, api_key=api_key)

    else:
        logger.warning(f"Unknown provider '{provider}'. Defaulting to Gemini.")
        return get_llm(step=step, provider="gemini")

    _llm_instances[instance_key] = llm
    return llm


def get_hyde_llm() -> Any:
    return get_llm(step="rag_search")


def get_rerank_llm() -> Any:
    return get_llm(step="rag_search")
