from pydantic import BaseModel
from uuid import UUID

class QueryRequest(BaseModel):
    tenant_id: UUID
    query: str
    use_hyde: bool = False
    use_rerank: bool = False

class QueryResponse(BaseModel):
    answer: str
