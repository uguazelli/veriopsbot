import json
import os
import logging
from typing import Any, Dict
from sqlalchemy import select
from src.storage.engine import get_session
from src.models import GlobalConfig

logger = logging.getLogger(__name__)

_config_cache = None

async def load_config_from_db():
    global _config_cache
    config = {}

    # Load from JSON first
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config.update(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load config.json: {e}")

    # Load from DB
    try:
        async for session in get_session():
            result = await session.execute(select(GlobalConfig.config).order_by(GlobalConfig.id.desc()).limit(1))
            db_config = result.scalars().first()
            if db_config and isinstance(db_config, dict):
                config.update(db_config)
                logger.info("Loaded global config from database")
    except Exception as e:
        logger.warning(f"Could not load config from DB: {e}")

    _config_cache = config
    return _config_cache

def get_config(force_reload: bool = False) -> Dict[str, Any]:
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache

    # If not cached yet (e.g. called before app startup), try to load from file at least
    # We cannot load from DB synchronously here without a sync engine.
    # So we fall back to file-only or empty.

    config = {}
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_path):
         try:
             with open(config_path, "r") as f:
                 config.update(json.load(f))
         except Exception:
             pass

    # If we are here, it means load_config_from_db hasn't run or force_reload is True.
    # We implicitly set the cache to file-only config to avoid error.
    # The app startup should have called load_config_from_db to overlay DB settings.
    _config_cache = config
    return _config_cache

def get_llm_settings(step: str) -> Dict[str, str]:
    config = get_config()
    llm_config = config.get("llm_config", {})
    steps = llm_config.get("steps", {})

    step_config = steps.get(step, steps.get("generation", {
        "provider": "gemini",
        "model": "models/gemini-2.0-flash"
    }))

    return step_config

def get_global_setting(key: str, default: Any = None) -> Any:
    config = get_config()
    llm_config = config.get("llm_config", {})
    return llm_config.get(key, default)
