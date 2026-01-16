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
    REWRITE_SYSTEM_PROMPT,
    PRICING_SYSTEM_PROMPT,
    LEAD_CAPTURE_SYSTEM_PROMPT,
    HANDOFF_SYSTEM_PROMPT,
    CALENDAR_RESPONSE_SYSTEM_PROMPT,
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
        logger.error(f"Pricing Node LLM failed: {e}")
        return {"messages": [AIMessage(content="I'm having trouble checking the price list right now.")]}


async def lead_node(state: AgentState):
    """Handles lead qualification and capture."""
    last_msg = state["messages"][-1].content
    sender_name = state.get("sender_name", "")
    sender_email = state.get("sender_email", "")
    sender_phone = state.get("sender_phone", "")

    # Inject Context into Prompt
    prompt = LEAD_CAPTURE_SYSTEM_PROMPT.format(
        existing_name=sender_name,
        existing_email=sender_email,
        existing_phone=sender_phone
    )

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=settings.google_api_key,
        convert_system_message_to_human=True,
    )

    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=last_msg)
    ]

    try:
        response = await llm.ainvoke(messages)
        content = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)

        # Logic: If Qualified -> Sync
        if data.get("qualified"):
            # 3. CRM Sync Logic (Extracted from actions.py pattern)
            client_slug = state.get("client_slug")
            if client_slug:
                try:
                     async with async_session_maker() as session:
                        from app.models.client import Client
                        # Fetch Configs
                        stmt = select(ServiceConfig).join(Client).where(Client.slug == client_slug)
                        result = await session.execute(stmt)
                        service_config = result.scalars().first()
                        configs = service_config.config if service_config else {}

                        # Initialize CRMs
                        from app.integrations.espocrm import EspoClient
                        from app.integrations.hubspot import HubSpotClient

                        crms = []
                        espo_conf = configs.get("espocrm")
                        if espo_conf:
                            crms.append(EspoClient(base_url=espo_conf["base_url"], api_key=espo_conf["api_key"]))

                        hub_conf = configs.get("hubspot")
                        if hub_conf:
                            token = hub_conf.get("access_token") or hub_conf.get("api_key")
                            if token:
                                crms.append(HubSpotClient(access_token=token))

                        # Execute Sync
                        if crms:
                            logger.info(f"🚀 Syncing Lead to {len(crms)} CRMs...")
                            name = data.get("extracted_name", sender_name)
                            email = data.get("extracted_email", sender_email)
                            phone = data.get("extracted_phone", sender_phone)

                            for crm in crms:
                                try:
                                    await crm.sync_lead(name=name, email=email, phone_number=phone)
                                    logger.info(f"✅ Lead synced to {crm.__class__.__name__}")
                                except Exception as crm_err:
                                    logger.error(f"❌ Lead sync failed for {crm.__class__.__name__}: {crm_err}")
                except Exception as sync_err:
                    logger.error(f"Lead Node Sync Error: {sync_err}")

        return {"messages": [AIMessage(content=data.get("response_message"))]}

    except Exception as e:
        logger.error(f"Lead Node failed: {e}")
        return {
            "messages": [AIMessage(content="I'm having a bit of trouble connecting to my lead system. I'll pass you to a human agent to help you out!")],
            "requires_human": True
        }





async def router_node(state: AgentState):
    last_msg = state["messages"][-1].content

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=settings.google_api_key,
        convert_system_message_to_human=True,  # Gemini sometimes prefers this
    )

    # Contextual Routing: Get previous AI message
    last_ai_msg = "None"
    if len(state["messages"]) >= 2:
        last_ai_msg = state["messages"][-2].content

    # Inject Context
    prompt_with_context = INTENT_SYSTEM_PROMPT + f"\n\nCONTEXT - Last Bot Message: '{last_ai_msg}'"

    messages = [SystemMessage(content=prompt_with_context + "\nJSON Output:"), HumanMessage(content=last_msg)]

    response = await llm.ainvoke(messages)
    content = response.content.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(content)
        intent = "rag"
        complexity = data.get("complexity_score", 5)
        pricing = data.get("pricing_intent", False)
        lead = data.get("lead_intent", False)

        if data.get("requires_human"):
            intent = "human"
        elif data.get("booking_intent"):
            # Calendar deactivated: Redirect to Human Handoff
            intent = "human"
        elif lead:
            intent = "lead"
        elif not data.get("requires_rag"):
            intent = "small_talk"
            complexity = 1
            pricing = False

        logger.info(
            f"Router Decision: {intent} (Reason: {data.get('reason')}) | Complexity: {complexity} | Pricing: {pricing} | Lead: {lead}"
        )

        return {"intent": intent, "complexity_score": complexity, "pricing_intent": pricing}

    except Exception as e:
        logger.error(f"Router failed: {e} | Content: {content}")
        return {"intent": "rag"}  # Fallback


async def human_handoff_node(state: AgentState):
    last_msg = state["messages"][-1].content

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
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
    """
    Revised Calendar Node:
    1. Extract Intent (Search, Verify, Confirm, Reject, Info).
    2. Handle Action Logic.
    3. Generate Localized Response.
    """
    logger.info("--- CALENDAR NODE (REVISED) ---")

    # 1. Setup & Config
    messages_history = state["messages"]
    last_msg = messages_history[-1].content

    # Init Config
    try:
        config_record = await get_service_config(state["tenant_id"])
        cal_config = config_record.config.get("calendar", {})
        calendar_provider = get_calendar_provider(cal_config)
    except Exception as e:
        logger.error(f"Calendar config error: {e}")
        return {"messages": [AIMessage(content="Sorry, I cannot access the calendar configuration.")]}

    # 2. Extract Intent using LLM
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash", temperature=0, google_api_key=settings.google_api_key
    )

    # Simplify history for context
    history_str = "\n".join([f"{m.type}: {m.content}" for m in messages_history[-6:]])

    extract_prompt = CALENDAR_EXTRACT_SYSTEM_PROMPT.format(current_time=datetime.datetime.utcnow().isoformat())
    extract_messages = [
        SystemMessage(content=extract_prompt),
        HumanMessage(content=f"HISTORY:\n{history_str}\n\nLAST MESSAGE: {last_msg}")
    ]

    action = "search"
    chosen_time = None
    email = None

    try:
        res = await llm.ainvoke(extract_messages)
        clean_json = res.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)
        action = data.get("action", "search")
        chosen_time = data.get("chosen_time")
        email = data.get("email")
        logger.info(f"CALENDAR ACTION: {action} | Time: {chosen_time} | Email: {email}")
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        # Default to search if confused
        action = "search"

    # 3. Handle Actions
    system_response = ""
    requires_human = False

    # Helper for Response Generation
    async def generate_response(sys_msg: str) -> str:
        loc_llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash", temperature=0.3, google_api_key=settings.google_api_key
        )
        # Pass full history to help with language detection
        hist_context = messages_history[-3:]
        prompt = CALENDAR_RESPONSE_SYSTEM_PROMPT.format(system_message=sys_msg)
        msgs = [SystemMessage(content=prompt)] + hist_context
        res = await loc_llm.ainvoke(msgs)
        return res.content

    try:
        if action == "reject_suggestions":
            system_response = "I understand. I will transfer you to a human agent to help find a better time."
            requires_human = True

        elif action == "search":
            # Search next 30 days
            start = datetime.datetime.utcnow()
            end = start + datetime.timedelta(days=30)
            slots = calendar_provider.get_available_slots(start, end)

            if slots:
                # Offer top 3 slots
                formatted_slots = [s.strftime("%A, %d %B at %H:%M") for s in slots[:3]]
                slots_str = "\n".join(f"- {s}" for s in formatted_slots)
                system_response = f"I found these available times in the next 30 days:\n{slots_str}\n\nDo any of these work for you?"
            else:
                system_response = "I could not find any available slots in the next 30 days. I will connect you with a human agent."
                requires_human = True

        elif action == "verify_slot":
            if chosen_time:
                # Ask for confirmation
                dt = datetime.datetime.fromisoformat(chosen_time.replace("Z", "+00:00"))
                readable = dt.strftime("%A, %d %B at %H:%M")
                system_response = f"Just to check: You would like to book for {readable}. Is this correct?"
            else:
                system_response = "I didn't catch the exact time. Which date and time would you like?"

        elif action == "confirm_booking" or action == "provide_info":
            # User said YES or gave EMAIL. Try to book.
            # We need both TIME and EMAIL.
            # If time is missing in extraction (context lost), we fallback to search.
            if not chosen_time:
                 system_response = "I lost track of the time you wanted. Could you please say the date and time again?"
            elif not email:
                 # Check if we have email in state (future enhancement) or just ask
                 system_response = "Great! To complete the booking, I just need your email address."
            else:
                # Try to book
                dt = datetime.datetime.fromisoformat(chosen_time.replace("Z", "+00:00"))
                link = calendar_provider.book_slot(start_time=dt, email=email)
                if link:
                    system_response = f"Booking confirmed! Here is your meeting link: {link}"
                else:
                    system_response = "I tried to book but that slot seems to be taken now. Let's try another time?"

        # 4. Generate Final Localized Response
        final_msg = await generate_response(system_response)

        return {
            "messages": [AIMessage(content=final_msg)],
            "requires_human": requires_human
        }

    except Exception as e:
        logger.error(f"Action Execution Failed: {e}")
        return {"messages": [AIMessage(content="Sorry, I encountered an error. Please try again.")]}
