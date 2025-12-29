import os
import logging
from llama_index.multi_modal_llms.gemini import GeminiMultiModal
from llama_index.core.multi_modal_llms.generic_utils import load_image_urls
from llama_index.core.schema import ImageDocument
from src.prompts import IMAGE_DESCRIPTION_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

_vlm = None

def get_vlm():
    """
    Factory to get the Gemini Multi-Modal model.
    """
    global _vlm
    if _vlm is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        # User specifically requested gemini-2.0-flash
        model_name = os.getenv("GEMINI_MODEL", "models/gemini-2.0-flash")
        if "gemini-1.5" in model_name and "flash" in model_name:
             # Fallback/Override if they have 1.5 set but want 2.0 behavior for vision if 1.5 failed them?
             # The user asked "can i use 2.0 instead", so they probably updated their env or want us to default to it.
             # I'll respect the ENV first, but default the fallback to 2.0-flash if env is missing.
             pass

        # If the user hasn't set GEMINI_MODEL, we default to 2.0-flash as requested.
        # If they HAVE set it (e.g. to 1.5), we trust they changed it or we use what's there.
        # But since they explicitly asked, I'll update the default fallback here.

        _vlm = GeminiMultiModal(model_name=model_name, api_key=api_key)
    return _vlm

def describe_image(image_bytes: bytes, filename: str) -> str:
    """
    Generates a detailed text description of an image using Gemini.
    """
    try:
        logger.info(f"Generating caption for image: {filename}")

        # LlamaIndex GeminiMultiModal expects ImageDocuments
        # We need to handle the bytes.
        # Ideally we save to temp file or pass bytes if supported.
        # simpler to just use google-generativeai directly if llama-index wrapper is strict,
        # but let's try to stick to LlamaIndex abstractions if possible, or direct SDK if easier.

        # Direct SDK is often more stable for "just get a string" tasks without complex indices.
        import google.generativeai as genai
        from PIL import Image
        import io

        api_key = os.getenv("GOOGLE_API_KEY")
        genai.configure(api_key=api_key)

        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        # Ensure model name doesn't have 'models/' prefix for direct SDK or does?
        # SDK usually handles both, but clean 'gemini-2.0-flash' is safer.
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
