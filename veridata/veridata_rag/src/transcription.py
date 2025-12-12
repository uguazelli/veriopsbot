import os
import io
import logging
from typing import Optional
import google.generativeai as genai
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

async def transcribe_openai(file_bytes: bytes, filename: str = "audio.mp3") -> str:
    """
    Transcribe audio using OpenAI Whisper.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    client = AsyncOpenAI(api_key=api_key)

    # OpenAI expects a file-like object with a name
    file_obj = io.BytesIO(file_bytes)
    file_obj.name = filename

    try:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=file_obj
        )
        return transcript.text
    except Exception as e:
        logger.error(f"OpenAI Transcription failed: {e}")
        raise e

async def transcribe_gemini(file_bytes: bytes, mime_type: str = "audio/mp3") -> str:
    """
    Transcribe audio using Google Gemini (GenAI).
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set")

    genai.configure(api_key=api_key)

    # Gemini Flash is good for this
    model_name = os.getenv("GEMINI_MODEL", "models/gemini-2.0-flash")
    model = genai.GenerativeModel(model_name)

    try:
        # For GenAI, we might need to upload the file or pass data inline.
        # Inline data is supported for smaller files.
        # Format: {"mime_type": ..., "data": ...}

        response = model.generate_content([
            "Transcribe this audio file exactly as spoken.",
            {
                "mime_type": mime_type,
                "data": file_bytes
            }
        ])
        return response.text
    except Exception as e:
        logger.error(f"Gemini Transcription failed: {e}")
        raise e

async def transcribe_audio(file_bytes: bytes, filename: str, provider: str = "gemini") -> str:
    """
    Router for transcription.
    """
    # Simple mime type guess
    mime_type = "audio/mp3"
    if filename.endswith(".ogg"):
        mime_type = "audio/ogg"
    elif filename.endswith(".wav"):
        mime_type = "audio/wav"
    elif filename.endswith(".m4a"):
        mime_type = "audio/mp4" # m4a is typically mp4 container

    if provider.lower() == "openai":
        return await transcribe_openai(file_bytes, filename)
    else:
        # Default to Gemini
        return await transcribe_gemini(file_bytes, mime_type)
