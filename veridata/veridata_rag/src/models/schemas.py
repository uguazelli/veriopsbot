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
    complexity_score: Optional[int] = 5
    pricing_intent: Optional[bool] = False
    external_context: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    session_id: Optional[UUID] = None
    context: Optional[str] = None


class SummarizeRequest(BaseModel):
    tenant_id: UUID
    session_id: UUID
    provider: Optional[str] = None


class ConversationSummary(BaseModel):
    purchase_intent: str  # High, Medium, Low, None
    urgency_level: str  # Urgent, Normal, Low
    sentiment_score: str  # Positive, Neutral, Negative
    detected_budget: Optional[Union[str, int, float]] = None
    ai_summary: str
    contact_info: Optional[dict] = {}  # phone, email, name, address, industry
    client_description: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str
    created_at: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    messages: list[ChatMessage]


class AppendMessageRequest(BaseModel):
    role: str
    content: str


class CreateSessionRequest(BaseModel):
    tenant_id: UUID


class CreateSessionResponse(BaseModel):
    session_id: UUID
