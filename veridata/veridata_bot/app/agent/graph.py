from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from app.agent.tools import lookup_pricing, search_knowledge_base, transfer_to_human
from app.core.config import settings
from app.agent.prompts import AGENT_SYSTEM_PROMPT

def build_agent():
    """
    Builds the ReAct Agent using LangGraph prebuilt.
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=0,
        google_api_key=settings.google_api_key,
    )

    tools = [search_knowledge_base, lookup_pricing, transfer_to_human]

    # We use LangGraph's prebuilt create_react_agent which handles the loop:
    # Agent -> Tool -> Agent ...

    # Use LangGraph's prebuilt create_react_agent
    # Passing system prompt via messages in engine.py to avoid version conflicts.
    agent = create_react_agent(llm, tools)

    return agent

# Global instance
agent_app = build_agent()
