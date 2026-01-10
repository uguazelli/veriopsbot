from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from app.agent.state import AgentState
from app.core.config import settings
from langchain_google_genai import ChatGoogleGenerativeAI
# from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from typing import Literal
import json
import logging
import os

logger = logging.getLogger(__name__)

# --- PROMPTS (Ported from RAG) ---

INTENT_SYSTEM_PROMPT = """You are a router. Analyze the user's query and decide on two things:
1. Does it require looking up external documents? (RAG)
2. Does the user explicitly ask to speak to a human agent? (HUMAN)

Rules for RAG:
1. Greetings, thanks, or personal questions -> RAG = FALSE
2. Questions about entities, products, policies, facts -> RAG = TRUE
3. Ambiguous questions -> RAG = TRUE
4. Unsure -> RAG = TRUE

Rules for HUMAN:
1. User says 'talk to human', 'real person', 'support agent', 'manager' -> HUMAN = TRUE
2. Otherwise -> HUMAN = FALSE

Complexity Analysis (COMPLEXITY):
Rank complexity from 1 to 10:
1-3: Simple greeting, thanks, or simple single-fact question.
4-6: Requires understanding context or summarizing a few points.
7-10: Requires multi-step reasoning, comparison, or handling ambiguous/creative requests.

Pricing/Product Intent (PRICING):
- Set 'pricing_intent' to true if user asks about: costs, prices, investment, specific products, availability, or ROI.
- Flag TRUE for keywords like: 'quanto custa', 'valor', 'preço', 'pagamento', 'investimento', 'disponibilidade', 'tempo de consultoria', 'hora'.

Return JSON with keys:
- 'requires_rag' (bool)
- 'requires_human' (bool)
- 'complexity_score' (int, 1-10)
- 'pricing_intent' (bool)
- 'reason' (short string)
"""

SMALL_TALK_SYSTEM_PROMPT = """You are Veribot 🤖, a helpful AI assistant.
Respond to the following user message nicely and concisely.
If this is a greeting, introduce yourself as Veribot 🤖, an AI assistant who can answer most questions or redirect you to a human agent.
IMPORTANT: Always answer in the same language as the user's message.
"""

# --- NODES ---

async def router_node(state: AgentState):
    """
    Analyzes the last message to decide the next step.
    Propagates the decision to the conditional edge.
    """
    last_msg = state["messages"][-1].content

    # Use Gemini Flash for speed/cost (equivalent to gpt-4o-mini)
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        convert_system_message_to_human=True # Gemini sometimes prefers this
    )

    # Note: Gemini JSON mode is a bit specific, usually prompts need to imply it strongly
    # or use .with_structured_output if available. For now we rely on prompt instruction + json parse.

    messages = [
        SystemMessage(content=INTENT_SYSTEM_PROMPT + "\nJSON Output:"),
        HumanMessage(content=last_msg)
    ]

    response = await llm.ainvoke(messages)
    # Clean the response content to handle markdown code blocks
    content = response.content.replace('```json', '').replace('```', '').strip()

    try:
        data = json.loads(content)
        intent = "rag"
        if data.get("requires_human"):
            intent = "human"
        elif not data.get("requires_rag"):
            intent = "small_talk"

        complexity = data.get("complexity_score", 5)
        pricing = data.get("pricing_intent", False)

        logger.info(f"Router Decision: {intent} (Reason: {data.get('reason')}) | Complexity: {complexity} | Pricing: {pricing}")

        return {
            "intent": intent,
            "complexity_score": complexity,
            "pricing_intent": pricing
        }

    except Exception as e:
        logger.error(f"Router failed: {e} | Content: {content}")
        return {"intent": "rag"} # Fallback

async def small_talk_node(state: AgentState):
    """Handles greetings and chitchat without RAG."""
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0.7,
        google_api_key=os.getenv("GOOGLE_API_KEY")
    )
    messages = [SystemMessage(content=SMALL_TALK_SYSTEM_PROMPT)] + state["messages"]

    response = await llm.ainvoke(messages)
    return {"messages": [response]}

async def human_handoff_node(state: AgentState):
    """Handles requests for a human agent."""
    return {
        "messages": [AIMessage(content="I understand you want to speak to a human. I am notifying a support agent to take over this chat.")],
        "requires_human": True
    }

from app.integrations.rag import RagClient
from app.core.config import settings
import uuid

async def rag_node(state: AgentState):
    """
    Prepares the query for the RAG service.
    Calls the actual 'veridata_rag' API via RagClient.
    """
    last_msg = state["messages"][-1].content

    rag_url = str(settings.rag_service_url)
    rag_key = settings.rag_api_key

    # Use context from state, fallback to dummy for safety/testing
    raw_tenant_id = state.get("tenant_id")
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

    session_id = state.get("session_id") # Can be None/Empty string

    # Ensure Session ID is a valid UUID or None
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

    try:
        response_data = await client.query(
            message=last_msg,
            session_id=session_uuid,
            complexity_score=complexity_score,
            pricing_intent=pricing_intent,
            google_sheets_url=google_sheets_url
        )

        rag_response = response_data.get("answer", "No answer returned.")
        requires_human = response_data.get("requires_human", False)

        return {
            "messages": [AIMessage(content=rag_response)],
            "requires_human": requires_human
        }

    except Exception as e:
        logger.error(f"RAG Service call failed: {e}")
        return {"messages": [AIMessage(content="I'm having trouble connecting to my knowledge base right now.")]}
