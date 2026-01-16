import logging
from sqlalchemy import select
from src.storage.engine import get_session
from src.models.db import GlobalConfig

logger = logging.getLogger(__name__)


async def get_rag_global_config() -> dict:
    """
    Fetches the full LLM configuration from GlobalConfig table.
    Returns a dict with:
      - model_name: str (default: None, implies fallback to env)
      - use_hyde: bool (default: None)
      - use_rerank: bool (default: None)
    """
    defaults = {
        "model_name": None,
        "use_hyde": None,
        "use_rerank": None
    }

    try:
        async for session in get_session():
            # Get the latest config
            stmt = select(GlobalConfig).order_by(GlobalConfig.id.desc()).limit(1)
            result = await session.execute(stmt)
            config_record = result.scalars().first()

            if config_record and config_record.config:
                llm_cfg = config_record.config.get("llm_config", {})

                # Extract flags
                defaults["use_hyde"] = llm_cfg.get("use_hyde")
                defaults["use_rerank"] = llm_cfg.get("use_rerank")

                # Extract model name
                # JSON Path: llm_config -> steps -> complex_reasoning -> model
                model_path = llm_cfg.get("steps", {}).get("complex_reasoning", {}).get("model")
                if model_path:
                    defaults["model_name"] = model_path.replace("models/", "")

            # We only need one session yield
            break

    except Exception as e:
        logger.error(f"Failed to fetch GlobalConfig from DB: {e}")

    return defaults
