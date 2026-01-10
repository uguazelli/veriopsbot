from typing import TypedDict, Annotated, List
from langchain_core.messages import BaseMessage
import operator

class AgentState(TypedDict):
    """The state of the agent's conversation."""
    # The 'messages' key will contain a list of messages.
    # The 'operator.add' reducer ensures that when a node returns new messages,
    # they are appended to the existing list rather than overwriting it.
    messages: Annotated[List[BaseMessage], operator.add]

    # user_id: str
    intent: str
    tenant_id: str
    session_id: str
    requires_human: bool
    complexity_score: int
    pricing_intent: bool
    google_sheets_url: str
