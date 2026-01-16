import json
import logging
import uuid

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.integrations.rag import RagClient

logger = logging.getLogger(__name__)

from app.agent.prompts import SUMMARY_PROMPT_TEMPLATE


async def summarize_start_conversation(
    session_id: uuid.UUID, rag_client: RagClient, language_instruction: str = None
) -> dict:
    """Fetch history from RAG and generate CRM summary using local LLM logic.
    """
    try:
        # 1. Fetch History from RAG
        history_list = await rag_client.get_history(session_id)
        if not history_list:
            logger.warning(f"No history found for session {session_id}")
            return {
                "purchase_intent": "None",
                "urgency_level": "Low",
                "sentiment_score": "Neutral",
                "ai_summary": "No history available.",
                "detected_budget": None,
                "detected_language": None,
                "contact_info": {},
            }

        # Format history
        history_str = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history_list])

        # 2. Local Summarization with Gemini
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0, google_api_key=settings.google_api_key)

        # Prepare Language Instruction
        lang_directive = ""
        if language_instruction:
            lang_directive = f"\n\nIMPORTANT: You MUST write the 'ai_summary' and 'client_description' in {language_instruction}."

        prompt = SUMMARY_PROMPT_TEMPLATE.format(history_str=history_str, language_instruction=lang_directive)
        messages = [HumanMessage(content=prompt)]

        response = await llm.ainvoke(messages)
        text = response.content.replace("```json", "").replace("```", "").strip()

        try:
            summary_json = json.loads(text)

            # Extract start time from the first message
            start_time = None
            if history_list and "created_at" in history_list[0] and history_list[0]["created_at"]:
                start_time = history_list[0]["created_at"]

            summary_json["session_start_time"] = start_time
            return summary_json

        except json.JSONDecodeError:
            logger.error(f"JSON decode failed for summary: {text}")
            return {
                "purchase_intent": "None",
                "urgency_level": "Low",
                "sentiment_score": "Neutral",
                "ai_summary": "Summarization failed (JSON error).",
                "detected_budget": None,
                "detected_language": None,
                "contact_info": {},
            }

    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return {
            "purchase_intent": "None",
            "urgency_level": "Low",
            "sentiment_score": "Neutral",
            "ai_summary": f"Error: {str(e)}",
            "detected_budget": None,
            "detected_language": None,
            "contact_info": {},
        }
