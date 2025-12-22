import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db

router = APIRouter(prefix="/api", tags=["api"])

class DebugRAGRequest(BaseModel):
    client_id: int
    text: str
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

@router.post("/debug/rag")
async def debug_rag(payload: DebugRAGRequest, db: AsyncSession = Depends(get_db)):
    messaging_service = MessagingService(db)

    # Verify RAG config exists for client
    rag_config = await messaging_service.get_integration_config(payload.client_id, "rag")
    if not rag_config:
        raise HTTPException(status_code=404, detail="RAG configuration not found for this client")

    from app.services.rag import RAGService
    rag_service = RAGService()

    answer = await rag_service.query(payload.text, payload.session_id, rag_config.settings)

    return {"response": answer}
