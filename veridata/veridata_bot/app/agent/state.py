import operator
from typing import Annotated, List, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    user_id: str
    intent: str
    tenant_id: str
    session_id: str
    requires_human: bool
    complexity_score: int
    pricing_intent: bool
    google_sheets_url: str
    retry_count: int
    grading_reason: str
