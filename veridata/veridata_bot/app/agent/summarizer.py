import logging
import json
import uuid
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from app.core.config import settings
from app.agent.prompts import SUMMARY_PROMPT_TEMPLATE
from app.integrations.rag import RagClient

logger = logging.getLogger(__name__)

async def summarize_start_conversation(
    session_id: uuid.UUID,
    rag_client: RagClient,
    language_instruction: str = None
) -> dict:
    """
    Fetches chat history from RAG and generates a structured summary using Gemini.
    """
    try:
        # 1. Fetch History
        history_data = await rag_client.get_history(session_id)
        if not history_data:
            logger.warning("No history found for summarization.")
            return {}

        # Format history for prompt
        history_str = ""
        first_msg_time = None

        for msg in history_data:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp") # Assuming RAG returns this?

            # Capture start time if available in metadata
            if not first_msg_time and timestamp:
                first_msg_time = timestamp

            history_str += f"{role.upper()}: {content}\n"

        # 2. Prepare Prompt
        lang_instr = f"IMPORTANT: Detected Language Override: {language_instruction}" if language_instruction else ""

        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            history_str=history_str,
            language_instruction=lang_instr
        )

        # 3. Call LLM
        model = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            temperature=0,
            google_api_key=settings.google_api_key,
        )

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content="Analyze the conversation now.")
        ]

        response = await model.ainvoke(messages)
        content = response.content.replace("```json", "").replace("```", "").strip()

        # 4. Parse JSON
        try:
            summary_data = json.loads(content)
            # Inject start time availability check
            if first_msg_time:
                 summary_data["session_start_time"] = first_msg_time
            return summary_data

        except json.JSONDecodeError:
            logger.error(f"Failed to parse summary JSON: {content}")
            return {"ai_summary": content} # Fallback

    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return {}
