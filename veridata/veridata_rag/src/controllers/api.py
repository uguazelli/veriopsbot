from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional
from uuid import UUID
from src.schemas import QueryRequest, QueryResponse, SummarizeRequest, ConversationSummary, ChatHistoryResponse
from src.rag import generate_answer
from src.memory import create_session, delete_session


router = APIRouter()

@router.delete("/session/{session_id}")
async def api_delete_session(session_id: UUID):
    delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}

@router.get("/session/{session_id}/history", response_model=ChatHistoryResponse)
async def api_get_history(session_id: UUID):
    from src.memory import get_full_chat_history
    history = get_full_chat_history(session_id)
    # Convert list of dicts to list of ChatMessage
    return {"messages": history}

@router.post("/query", response_model=QueryResponse)
async def api_query_rag(request: QueryRequest):
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
        session_id=session_id,
        handoff_rules=request.handoff_rules,

        complexity_score=request.complexity_score,
        pricing_intent=request.pricing_intent,
        external_context=request.external_context
    )
    return QueryResponse(
        answer=answer,
        requires_human=requires_human,
        session_id=session_id
    )




