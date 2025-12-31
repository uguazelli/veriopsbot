from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional
from uuid import UUID
from src.schemas import QueryRequest, QueryResponse, SummarizeRequest, ConversationSummary
from src.rag import generate_answer, summarize_conversation
from src.memory import create_session, delete_session
from src.transcription import transcribe_audio

router = APIRouter()

@router.delete("/session/{session_id}")
async def api_delete_session(session_id: UUID):
    delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}

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
        google_sheets_url=request.google_sheets_url
    )
    return QueryResponse(
        answer=answer,
        requires_human=requires_human,
        session_id=session_id
    )

@router.post("/summarize", response_model=ConversationSummary)
async def api_summarize_conversation(request: SummarizeRequest):
    summary_data = summarize_conversation(request.session_id, request.provider)
    return ConversationSummary(**summary_data)


@router.post("/transcribe")
async def api_transcribe(file: UploadFile = File(...), provider: Optional[str] = Form(None)):
    content = await file.read()
    text = await transcribe_audio(content, file.filename, provider)

    return {"text": text}
