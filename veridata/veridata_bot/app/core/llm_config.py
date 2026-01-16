from sqlalchemy import select
from app.core.db import async_session_maker
from app.models.config import GlobalConfig
import logging

logger = logging.getLogger(__name__)

async def get_llm_config() -> dict:
    """
    Fetches the full LLM configuration from GlobalConfig.
    Returns a dict with:
      - model_name: str (default: "gemini-2.0-flash")
      - use_hyde: bool (default: False)
      - use_rerank: bool (default: False)
    """
    defaults = {
        "model_name": "gemini-2.0-flash",
        "use_hyde": False,
        "use_rerank": False
    }

    try:
        async with async_session_maker() as session:
            stmt = select(GlobalConfig).limit(1)
            result = await session.execute(stmt)
            config_record = result.scalars().first()

            if config_record and config_record.config:
                llm_cfg = config_record.config.get("llm_config", {})

                # Extract flags
                defaults["use_hyde"] = llm_cfg.get("use_hyde", False)
                defaults["use_rerank"] = llm_cfg.get("use_rerank", False)

                # Extract model name
                # JSON Path: llm_config -> steps -> complex_reasoning -> model
                model_path = llm_cfg.get("steps", {}).get("complex_reasoning", {}).get("model")
                if model_path:
                    defaults["model_name"] = model_path.replace("models/", "")

    except Exception as e:
        logger.error(f"Failed to fetch GlobalConfig: {e}")

    return defaults
