from fastapi import APIRouter, Depends
from src.schemas import QueryRequest, QueryResponse
from src.auth import get_current_username
from src.rag import generate_answer

router = APIRouter()

@router.post("/query", response_model=QueryResponse)
async def api_query_rag(
    request: QueryRequest,
    username: str = Depends(get_current_username)
):
    """
    External API endpoint to query the RAG engine.
    Authentication: Basic Auth (admin/admin).
    Payload: {"tenant_id": "uuid", "query": "str"}
    """
    answer = generate_answer(
        request.tenant_id,
        request.query,
        use_hyde=request.use_hyde,
        use_rerank=request.use_rerank
    )
    return QueryResponse(answer=answer)
