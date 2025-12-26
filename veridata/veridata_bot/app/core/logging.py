import logging
import logging.config
import sys
import json
import os
from datetime import datetime

# Emojis for Visual Grepping
EMOJI_PAYLOAD = "📦"
EMOJI_FLOW_START = "🚀"
EMOJI_FLOW_END = "🏁"
EMOJI_FLOW_SKIP = "⏭️"
EMOJI_SUCCESS = "✅"
EMOJI_ERROR = "❌"
EMOJI_DB = "💾"
EMOJI_EXT_SERVICE = "🌐"
EMOJI_CONFIG = "⚙️"

class PrettyJSONFormatter(logging.Formatter):
    """
    Formatter that dumps dict/list message arguments as pretty JSON.
    """
    def format(self, record):
        # Allow passing a dict/list as the message directly
        if isinstance(record.msg, (dict, list)):
             try:
                 record.msg = f"\n{json.dumps(record.msg, indent=2, default=str)}"
             except Exception:
                 pass
        return super().format(record)

def setup_logging(log_level=logging.INFO, log_dir="logs", log_filename="veridata_bot.log"):
    """
    Configures logging with Console and Rotating File handlers.
    """
    # Ensure log directory exists
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file_path = os.path.join(log_dir, log_filename)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            },
            "pretty": {
                "()": PrettyJSONFormatter,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "pretty",
                "level": log_level
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_file_path,
                "maxBytes": 10 * 1024 * 1024, # 10 MB
                "backupCount": 5,
                "formatter": "pretty",
                "level": log_level,
                "encoding": "utf-8"
            }
        },
        "root": {
            "handlers": ["console", "file"],
            "level": log_level
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False
            },
            "sqlalchemy.engine": {
                "handlers": ["console", "file"],
                "level": "WARNING", # Prevent SQL spam unless debugging
                "propagate": False
            }
        }
    }

    logging.config.dictConfig(logging_config)

# Helper functions for standardized logging
def log_payload(logger, payload, msg="Payload Received"):
    try:
        # Manually pretty print to ensure it survives f-strings
        pretty_payload = json.dumps(payload, indent=2, default=str)
        logger.info(f"{EMOJI_PAYLOAD} {msg}:\n{pretty_payload}")
    except Exception:
        # Fallback
        logger.info(f"{EMOJI_PAYLOAD} {msg}: {payload}")

def log_start(logger, msg):
    logger.info(f"{EMOJI_FLOW_START} {msg}")

def log_end(logger, msg):
    logger.info(f"{EMOJI_FLOW_END} {msg}")

def log_skip(logger, msg):
    logger.info(f"{EMOJI_FLOW_SKIP} {msg}")

def log_success(logger, msg):
    logger.info(f"{EMOJI_SUCCESS} success: {msg}")

def log_error(logger, msg, exc_info=False):
    logger.error(f"{EMOJI_ERROR} error: {msg}", exc_info=exc_info)

def log_external_call(logger, service, msg):
    logger.info(f"{EMOJI_EXT_SERVICE} Call to {service}: {msg}")

def log_db(logger, msg):
    logger.info(f"{EMOJI_DB} DB: {msg}")
