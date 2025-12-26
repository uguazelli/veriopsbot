from pydantic import BaseModel
from uuid import UUID
from typing import Optional, Union

class QueryRequest(BaseModel):
    tenant_id: UUID
    query: str
    use_hyde: bool = False
    use_rerank: bool = False
    provider: str = "gemini"
    session_id: Optional[UUID] = None

class QueryResponse(BaseModel):
    answer: str
    requires_human: bool = False
    session_id: Optional[UUID] = None

class SummarizeRequest(BaseModel):
    tenant_id: UUID
    session_id: UUID
    provider: str = "gemini"

class ConversationSummary(BaseModel):
    purchase_intent: str # High, Medium, Low, None
    urgency_level: str # Urgent, Normal, Low
    sentiment_score: str # Positive, Neutral, Negative
    detected_budget: Optional[Union[str, int, float]] = None
    ai_summary: str
    contact_info: Optional[dict] = {} # phone, email, name, address, industry
    client_description: Optional[str] = None
