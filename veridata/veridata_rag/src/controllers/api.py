from fastapi import APIRouter, UploadFile, File, Form
from uuid import UUID
from src.services.rag import generate_answer
from src.services.vlm import describe_image
from src.models.schemas import QueryRequest, QueryResponse, ChatMessage, ChatHistoryResponse
from src.services.memory import get_full_chat_history, create_session, delete_session
from src.config.logging import log_start, log_success, log_error

router = APIRouter()

# ==================================================================================
# API: SESSION
# CLEANUP
# Removes session history from Postgres/Memory.
# ==================================================================================
@router.delete("/session/{session_id}")
async def api_delete_session(session_id: UUID):
    await delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}


# ==================================================================================
# API: HISTORY
# CONTEXT
# Retrieves the full chat transcript.
# Used by bot/engine.py to feed LangGraph or for Summarization.
# ==================================================================================
@router.get("/session/{session_id}/history", response_model=ChatHistoryResponse)
async def api_get_history(session_id: UUID):
    history = await get_full_chat_history(session_id)
    return {"messages": history}


# ==================================================================================
# API: QUERY RAG
# The primary endpoint.
# Receives user text + metadata (Pricing/Complexity).
# Returns: Answer + Handoff Flag + Session ID.
# ==================================================================================
@router.post("/query", response_model=QueryResponse)
async def api_query_rag(request: QueryRequest):
    session_id = request.session_id
    if not session_id:
        session_id_str = await create_session(request.tenant_id)
        session_id = UUID(session_id_str)

    answer, requires_human = await generate_answer(
        request.tenant_id,
        request.query,
        use_hyde=request.use_hyde,
        use_rerank=request.use_rerank,
        provider=request.provider,
        session_id=session_id,
        complexity_score=request.complexity_score,
        pricing_intent=request.pricing_intent,
        external_context=request.external_context
    )
    return QueryResponse(
        answer=answer,
        requires_human=requires_human,
        session_id=session_id
    )




