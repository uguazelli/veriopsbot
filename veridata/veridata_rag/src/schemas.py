from pydantic import BaseModel
from uuid import UUID
from typing import Optional

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
