import json
import logging
import uuid
from app.integrations.rag import RagClient
from app.integrations.sheets import fetch_google_sheet_data
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from app.agent.state import AgentState
from app.core.config import settings
from app.core.llm_config import get_llm_config
from app.agent.prompts import (
    INTENT_SYSTEM_PROMPT,
    SMALL_TALK_SYSTEM_PROMPT,
    GRADER_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    PRICING_SYSTEM_PROMPT,
    HANDOFF_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


async def pricing_node(state: AgentState):
    """Handles pricing and product queries with strict enforcement."""
    last_msg = state["messages"][-1].content
    google_sheets_url = state.get("google_sheets_url")

    # 1. Fetch Product Data (Strictly from Sheet)
    product_context = "No product data available."
    if google_sheets_url:
        try:
            logger.info(f"💲 Pricing Node: Fetching data from {google_sheets_url}...")
            product_context = await fetch_google_sheet_data(google_sheets_url)
        except Exception as e:
            logger.error(f"Pricing Node failed to fetch sheet: {e}")
            product_context = "Error loading product data."

    # 2. Call LLM as Sales Enforcer
    config = await get_llm_config()
    llm = ChatGoogleGenerativeAI(
        model=config["model_name"],
        temperature=0, # ZERO temperature for strict adherence
        google_api_key=settings.google_api_key,
    )

    messages = [
        SystemMessage(content=PRICING_SYSTEM_PROMPT),
        HumanMessage(content=f"PRODUCT DATA:\n{product_context}\n\nUSER QUESTION:\n{last_msg}"),
    ]

    try:
        response = await llm.ainvoke(messages)
        return {"messages": [AIMessage(content=response.content)]}
    except Exception as e:
        logger.error(f"Pricing Node LLM failed: {e}")
        logger.error(f"Pricing Node LLM failed: {e}")
        return {"messages": [AIMessage(content="I'm having trouble checking the price list right now.")]}


async def router_node(state: AgentState):
    last_msg = state["messages"][-1].content

    config = await get_llm_config()
    llm = ChatGoogleGenerativeAI(
        model=config["model_name"],
        temperature=0,
        google_api_key=settings.google_api_key,
        convert_system_message_to_human=True,  # Gemini sometimes prefers this
    )

    # Contextual Routing: Get last 6 messages for full context
    recent_msgs = state["messages"][-6:]
    history_str = ""
    for msg in recent_msgs:
        role = "User" if isinstance(msg, (HumanMessage, str)) and (not hasattr(msg, "type") or msg.type == "human") else "Bot"
        # Safety check for content
        content = getattr(msg, "content", str(msg))
        history_str += f"{role}: {content}\n"

    # Inject Context
    prompt_with_context = INTENT_SYSTEM_PROMPT + f"\n\n### CONVERSATION HISTORY (CTX):\n{history_str}"

    messages = [SystemMessage(content=prompt_with_context + "\nJSON Output:"), HumanMessage(content=last_msg)]

    response = await llm.ainvoke(messages)
    content = response.content.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(content)
        intent = "rag"
        complexity = data.get("complexity_score", 5)
        pricing = data.get("pricing_intent", False)
        pricing = data.get("pricing_intent", False)

        if data.get("requires_human"):
            intent = "human"
        elif not data.get("requires_rag"):
            intent = "small_talk"
            complexity = 1
            pricing = False

        logger.info(
            f"Router Decision: {intent} (Reason: {data.get('reason')}) | Complexity: {complexity} | Pricing: {pricing}"
        )

        return {"intent": intent, "complexity_score": complexity, "pricing_intent": pricing}

    except Exception as e:
        logger.error(f"Router failed: {e} | Content: {content}")
        return {"intent": "rag"}  # Fallback


async def human_handoff_node(state: AgentState):
    last_msg = state["messages"][-1].content

    config = await get_llm_config()
    llm = ChatGoogleGenerativeAI(
        model=config["model_name"],
        temperature=0,
        google_api_key=settings.google_api_key,
    )

    messages = [
        SystemMessage(content=HANDOFF_SYSTEM_PROMPT),
        HumanMessage(content=last_msg),
    ]

    try:
        response = await llm.ainvoke(messages)
        handoff_msg = response.content
    except Exception as e:
        logger.error(f"Handoff LLM failed: {e}")
        handoff_msg = "I am connecting you to a human agent now."

    return {
        "messages": [AIMessage(content=handoff_msg)],
        "requires_human": True,
    }


async def small_talk_node(state: AgentState):
    """Handles small talk and greetings without RAG."""
    last_msg = state["messages"][-1].content

    config = await get_llm_config()
    llm = ChatGoogleGenerativeAI(
        model=config["model_name"],
        temperature=0.7, # Slightly higher temperature for friendly chat
        google_api_key=settings.google_api_key,
    )

    messages = [
        SystemMessage(content=SMALL_TALK_SYSTEM_PROMPT),
        HumanMessage(content=last_msg),
    ]

    try:
        response = await llm.ainvoke(messages)
        return {"messages": [AIMessage(content=response.content)]}
    except Exception as e:
        logger.error(f"Small Talk failed: {e}")
        return {"messages": [AIMessage(content="Hello! How can I help you today?")]}


async def grader_node(state: AgentState):
    """Grades the RAG response for relevance/hallucinations."""
    last_msg = state["messages"][-1].content  # The RAG Answer
    # We need the User Question. It's usually the second to last, OR the last "HumanMessage"
    # To be safe, let's find the last HumanMessage
    user_question = "Unknown"
    for msg in reversed(state["messages"][:-1]):
        if isinstance(msg, HumanMessage):
            user_question = msg.content
            break

    config = await get_llm_config()
    llm = ChatGoogleGenerativeAI(
        model=config["model_name"],
        temperature=0,
        google_api_key=settings.google_api_key,
    )

    # Get Context from State (populated by RAG Node)
    rag_context = state.get("rag_context") or "[Context Not Available]"

    formatted_prompt = GRADER_SYSTEM_PROMPT.format(
        context=rag_context,
        question=user_question,
        student_answer=last_msg
    )

    messages = [
        SystemMessage(content=formatted_prompt),
        HumanMessage(content="Please grade the above.")
    ]

    try:
        response = await llm.ainvoke(messages)
        content = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)
        score = data.get("score", 1)
        reason = data.get("reason", "No reason provided")
    except Exception as e:
        logger.error(f"Grader failed: {e}")
        score = 1  # Fallback to accepting it manually
        reason = "Grader Error"

    return {"grading_reason": f"SCORE: {score} | {reason}"}


async def rewrite_node(state: AgentState):
    """Rewrites the query to attempt a better RAG search."""
    user_question = state["messages"][-2].content  # Assuming User -> AI (bad).
    # Actually, the messages list grows.
    # [User, AI (bad)]
    grading_reason = state.get("grading_reason", "")

    config = await get_llm_config()
    llm = ChatGoogleGenerativeAI(
        model=config["model_name"],
        temperature=0,
        google_api_key=settings.google_api_key,
    )

    messages = [
        SystemMessage(content=REWRITE_SYSTEM_PROMPT),
        HumanMessage(content=f"ORIGINAL: {user_question}\nFAILURE REASON: {grading_reason}"),
    ]

    response = await llm.ainvoke(messages)
    new_query = response.content.strip()

    logger.info(f"🔄 Query Rewritten: '{user_question}' -> '{new_query}'")

    # We need to replace the last Human Message with this new query?
    # Or just append it?
    # If we append, the history grows: User, AI(bad), User(Rewritten).
    # Then RAG runs again. This is standard loop behavior.
    return {
        "messages": [HumanMessage(content=new_query)],
        "retry_count": state.get("retry_count", 0) + 1,
    }



async def rag_node(state: AgentState):
    last_msg = state["messages"][-1].content

    rag_url = str(settings.rag_service_url)
    rag_key = settings.rag_api_key
    raw_tenant_id = state.get("tenant_id")
    # Default to Dummy UUID for dev/test resilience if tenant context is missing
    tenant_id = "00000000-0000-0000-0000-000000000000"

    try:
        if raw_tenant_id:
            # Check if it's a valid UUID
            uuid.UUID(str(raw_tenant_id))
            tenant_id = str(raw_tenant_id)
        else:
            logger.warning(f"Tenant ID missing in state, using default: {tenant_id}")
    except ValueError:
        logger.warning(f"Invalid Tenant ID format '{raw_tenant_id}', using default: {tenant_id}")

    session_id = state.get("session_id")
    try:
        if session_id:
            session_uuid = uuid.UUID(session_id)
        else:
            session_uuid = None
    except:
        session_uuid = None

    client = RagClient(base_url=rag_url, api_key=rag_key, tenant_id=tenant_id)

    complexity_score = state.get("complexity_score", 5)
    pricing_intent = state.get("pricing_intent", False)
    google_sheets_url = state.get("google_sheets_url")

    external_context = None
    if google_sheets_url and pricing_intent:
        # Fetch data locally in the Bot ONLY if pricing/product intent is detected
        logger.info(f"📊 Fetching Google Sheet data from {google_sheets_url}...")
        external_context = await fetch_google_sheet_data(google_sheets_url)

    try:
        # Fetch dynamic config
        config = await get_llm_config()

        response_data = await client.query(
            message=last_msg,
            session_id=session_uuid,
            complexity_score=complexity_score,
            pricing_intent=pricing_intent,
            external_context=external_context,
            use_hyde=config["use_hyde"],
            use_rerank=config["use_rerank"],
        )

        rag_response = response_data.get("answer", "No answer returned.")
        requires_human = response_data.get("requires_human", False)
        new_session_id = response_data.get("session_id")
        context = response_data.get("context", "")

        return {
            "messages": [AIMessage(content=rag_response)],
            "requires_human": requires_human,
            "session_id": new_session_id,
            "history_saved": True,
            "rag_context": context,
        }

    except Exception as e:
        logger.error(f"RAG Service call failed: {e}")
        return {"messages": [AIMessage(content="I'm having trouble connecting to my knowledge base right now.")]}



