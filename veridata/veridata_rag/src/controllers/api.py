from fastapi import APIRouter, Depends, UploadFile, File, Form
from uuid import UUID
from src.schemas import QueryRequest, QueryResponse, SummarizeRequest, ConversationSummary
from src.auth import get_current_username
from src.rag import generate_answer, summarize_conversation
from src.memory import create_session
from src.transcription import transcribe_audio

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

@router.post("/summarize", response_model=ConversationSummary)
async def api_summarize_conversation(
    request: SummarizeRequest,
    username: str = Depends(get_current_username)
):
    """
    Summarizes a conversation session.
    """
    summary_data = summarize_conversation(request.session_id, request.provider)
    return ConversationSummary(**summary_data)


@router.post("/transcribe")
async def api_transcribe(
    file: UploadFile = File(...),
    provider: str = Form("gemini"),
    username: str = Depends(get_current_username)
):
    """
    Transcribes uploaded audio file.
    """
    content = await file.read()
    text = await transcribe_audio(content, file.filename, provider)

    return {"text": text}
