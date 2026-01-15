import json
import logging

import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

# from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.state import AgentState
from app.core.config import settings
from app.core.db import async_session_maker
from app.integrations.calendar.factory import get_calendar_provider
from app.models.config import ServiceConfig
from sqlalchemy import select
from app.agent.prompts import (
    INTENT_SYSTEM_PROMPT,
    SMALL_TALK_SYSTEM_PROMPT,
    GRADER_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    PRICING_SYSTEM_PROMPT,
)
from app.integrations.sheets import fetch_google_sheet_data

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
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
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
        return {"messages": [AIMessage(content="I'm having trouble checking the price list right now.")]}





async def router_node(state: AgentState):
    last_msg = state["messages"][-1].content

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=settings.google_api_key,
        convert_system_message_to_human=True,  # Gemini sometimes prefers this
    )

    messages = [SystemMessage(content=INTENT_SYSTEM_PROMPT + "\nJSON Output:"), HumanMessage(content=last_msg)]

    response = await llm.ainvoke(messages)
    content = response.content.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(content)
        intent = "rag"
        complexity = data.get("complexity_score", 5)
        pricing = data.get("pricing_intent", False)

        if data.get("requires_human"):
            intent = "human"
        elif data.get("booking_intent"):
            intent = "calendar"
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
    return {
        "messages": [
            AIMessage(
                content="I understand you want to speak to a human. I am notifying a support agent to take over this chat."
            )
        ],
        "requires_human": True,
    }


async def small_talk_node(state: AgentState):
    """Handles small talk and greetings without RAG."""
    last_msg = state["messages"][-1].content

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
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

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=settings.google_api_key,
    )

    messages = [
        SystemMessage(content=GRADER_SYSTEM_PROMPT),
        HumanMessage(content=f"QUESTION: {user_question}\nSTUDENT ANSWER: {last_msg}"),
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

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
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


import uuid

from app.integrations.rag import RagClient
from app.integrations.sheets import fetch_google_sheet_data


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
    if google_sheets_url:
        # Fetch data locally in the Bot
        logger.info(f"📊 Fetching Google Sheet data from {google_sheets_url}...")
        external_context = await fetch_google_sheet_data(google_sheets_url)

    try:
        response_data = await client.query(
            message=last_msg,
            session_id=session_uuid,
            complexity_score=complexity_score,
            pricing_intent=pricing_intent,
            external_context=external_context,
        )

        rag_response = response_data.get("answer", "No answer returned.")
        requires_human = response_data.get("requires_human", False)
        new_session_id = response_data.get("session_id")

        return {
            "messages": [AIMessage(content=rag_response)],
            "requires_human": requires_human,
            "session_id": new_session_id,
        }

    except Exception as e:
        logger.error(f"RAG Service call failed: {e}")
        return {"messages": [AIMessage(content="I'm having trouble connecting to my knowledge base right now.")]}


async def calendar_node(state: AgentState):
    """Handles calendar booking and availability checks."""
    last_msg = state["messages"][-1].content
    client_slug = state.get("client_slug")

    # 1. Fetch Calendar Config from DB
    calendar_provider = None
    if client_slug:
        try:
            async with async_session_maker() as session:
                logger.info(f"CALENDAR_DEBUG: Querying ServiceConfig for Client Slug: {client_slug}")
                # Assuming tenant_id maps to Client.slug (or modifying logic to match)
                from app.models.client import Client
                stmt = select(ServiceConfig).join(Client).where(Client.slug == client_slug)
                result = await session.execute(stmt)
                service_config = result.scalars().first()

                if service_config:
                    logger.info("CALENDAR_DEBUG: Found ServiceConfig record.")
                    if service_config.config:
                        logger.info(f"CALENDAR_DEBUG: ServiceConfig has keys: {list(service_config.config.keys())}")
                        calendar_config = service_config.config.get("calendar")
                        if calendar_config:
                            logger.info("CALENDAR_DEBUG: Found 'calendar' config block. Initializing provider...")
                            calendar_provider = get_calendar_provider(calendar_config)
                        else:
                            logger.warning("CALENDAR_DEBUG: 'calendar' key MISSING in ServiceConfig.")
                    else:
                        logger.warning("CALENDAR_DEBUG: ServiceConfig.config is EMPTY/None.")
                else:
                    logger.warning(f"CALENDAR_DEBUG: No ServiceConfig found in DB for client_slug='{client_slug}'")

        except Exception as e:
            logger.error(f"CALENDAR_DEBUG: Failed to load calendar config: {e}")
    else:
         logger.warning("CALENDAR_DEBUG: client_slug MISSING in AgentState. Cannot load calendar config.")

    if not calendar_provider:
        # Fallback or Error
        return {"messages": [AIMessage(content="I'm sorry, I cannot access the calendar configuration for this account.")]}

    # 2. Use LLM to extract booking details
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=settings.google_api_key,
        convert_system_message_to_human=True,
    )

    extraction_prompt = """Extract booking details from the message.
    Return JSON:
    {
        "action": "check_availability" or "book" or "list_slots",
        "start_time": "ISO string or null",
        "end_time": "ISO string or null (default start + 1h if missing)",
        "attendee_email": "email or null"
    }
    Current Time: """ + datetime.datetime.utcnow().isoformat()

    messages = [
        SystemMessage(content=extraction_prompt),
        HumanMessage(content=last_msg)
    ]

    try:
        response = await llm.ainvoke(messages)
        content = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)

        action = data.get("action")
        start_str = data.get("start_time")
        end_str = data.get("end_time")
        attendee = data.get("attendee_email")

        if not start_str and action != "list_slots":
            return {"messages": [AIMessage(content="I need to know the date and time you'd like to book.")]}

        start_time = None
        if start_str:
            start_time = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))

        end_time = None
        if end_str:
            end_time = datetime.datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        elif start_time:
            end_time = start_time + datetime.timedelta(hours=1)

        result_msg = ""
        if action == "check_availability":
            slots = calendar_provider.get_available_slots(start_time, end_time)
            is_free = len(slots) > 0
            result_msg = "Yes, that slot is available." if is_free else "Sorry, that slot is taken."

        elif action == "book":
            if not attendee:
                return {"messages": [AIMessage(content="I need your email address to send the invite.")]}

            link = calendar_provider.book_slot(
                start_time=start_time,
                email=attendee,
            )
            if link:
                result_msg = f"I've scheduled the meeting! {link}"
            else:
                result_msg = "I failed to schedule the meeting. Please try again."

        elif action == "list_slots":
            # Default to next 24 hours if no time range provided
            search_start = start_time if start_time else datetime.datetime.utcnow()
            search_end = end_time if end_time else search_start + datetime.timedelta(days=1)

            slots = calendar_provider.get_available_slots(search_start, search_end)

            if slots:
                # Format slots nicely
                slots_by_day = {}
                for slot in slots:
                    day_str = slot.strftime("%a, %b %d")
                    time_str = slot.strftime("%I:%M %p")
                    if day_str not in slots_by_day:
                        slots_by_day[day_str] = []
                    slots_by_day[day_str].append(time_str)

                msg_lines = [f"Here are some available times between {search_start.strftime('%b %d')} and {search_end.strftime('%b %d')}:"]
                for day, times in slots_by_day.items():
                    msg_lines.append(f"- **{day}**: {', '.join(times[:5])}")

                result_msg = "\n".join(msg_lines)
            else:
                result_msg = "I couldn't find any free slots in that time range."

        return {"messages": [AIMessage(content=result_msg)]}

    except Exception as e:
        logger.error(f"Calendar node failed: {e}")
        return {"messages": [AIMessage(content="Sorry, I couldn't access the calendar.")]}
