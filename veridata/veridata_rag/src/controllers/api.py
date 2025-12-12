from fastapi import APIRouter, Depends
from uuid import UUID
from src.schemas import QueryRequest, QueryResponse
from src.auth import get_current_username
from src.rag import generate_answer
from src.memory import create_session

router = APIRouter()

@router.post("/query", response_model=QueryResponse)
async def api_query_rag(
    request: QueryRequest,
    username: str = Depends(get_current_username)
):
    session_id = request.session_id
    if not session_id:
        session_id_str = create_session(request.tenant_id)
        session_id = UUID(session_id_str)

    answer, requires_human = generate_answer(
        request.tenant_id,
        request.query,
        use_hyde=request.use_hyde,
        use_rerank=request.use_rerank,
        provider=request.provider,
        session_id=session_id
    )
    return QueryResponse(
        answer=answer,
        requires_human=requires_human,
        session_id=session_id
    )
