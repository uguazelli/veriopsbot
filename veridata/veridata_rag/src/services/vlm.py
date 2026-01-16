import os
import logging
from llama_index.multi_modal_llms.gemini import GeminiMultiModal
from src.utils.prompts import IMAGE_DESCRIPTION_PROMPT_TEMPLATE
import google.generativeai as genai
from PIL import Image
import io
from src.config.config import get_llm_settings

logger = logging.getLogger(__name__)

_vlm = None


def get_vlm():
    global _vlm
    if _vlm is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "models/gemini-2.0-flash")
        _vlm = GeminiMultiModal(model_name=model_name, api_key=api_key)
    return _vlm


def describe_image(image_bytes: bytes, filename: str) -> str:
    try:
        logger.info(f"Generating caption for image: {filename}")
        api_key = os.getenv("GOOGLE_API_KEY")
        genai.configure(api_key=api_key)
        settings = get_llm_settings("complex_reasoning")
        model_name = settings.get(
            "model", os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        )
        clean_model = model_name.replace("models/", "")
        model = genai.GenerativeModel(clean_model)
        image = Image.open(io.BytesIO(image_bytes))
        prompt = IMAGE_DESCRIPTION_PROMPT_TEMPLATE
        response = model.generate_content([prompt, image])
        description = response.text
        logger.info(f"Caption generated: {description[:100]}...")
        return description

    except Exception as e:
        logger.error(f"VLM generation failed: {e}")
        return f"Image: {filename} (Description failed)"
