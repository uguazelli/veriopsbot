from pydantic import BaseModel
from uuid import UUID

class QueryRequest(BaseModel):
    tenant_id: UUID
    query: str

class QueryResponse(BaseModel):
    answer: str
