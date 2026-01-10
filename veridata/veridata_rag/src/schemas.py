from pydantic import BaseModel
from uuid import UUID
from typing import Optional, Union

class QueryRequest(BaseModel):
    tenant_id: UUID
    query: str
    use_hyde: Optional[bool] = None
    use_rerank: Optional[bool] = None
    provider: Optional[str] = None
    session_id: Optional[UUID] = None
    handoff_rules: Optional[str] = None
    google_sheets_url: Optional[str] = None
    complexity_score: Optional[int] = 5
    pricing_intent: Optional[bool] = False

class QueryResponse(BaseModel):
    answer: str
    requires_human: bool = False
    session_id: Optional[UUID] = None

class SummarizeRequest(BaseModel):
    tenant_id: UUID
    session_id: UUID
    provider: Optional[str] = None

class ConversationSummary(BaseModel):
    purchase_intent: str # High, Medium, Low, None
    urgency_level: str # Urgent, Normal, Low
    sentiment_score: str # Positive, Neutral, Negative
    detected_budget: Optional[Union[str, int, float]] = None
    ai_summary: str
    contact_info: Optional[dict] = {} # phone, email, name, address, industry
    client_description: Optional[str] = None
