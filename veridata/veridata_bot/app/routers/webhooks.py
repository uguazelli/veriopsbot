from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.messaging import MessagingService

from app.services.telegram import TelegramService

router = APIRouter(prefix="/webhook", tags=["webhooks"])

@router.post("/telegram/{token}")
async def receive_telegram_webhook(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messaging_service = MessagingService(db)
    telegram_service = TelegramService(messaging_service)

    await telegram_service.process_update(token, payload)

    return {"status": "received"}

@router.post("/{source}")
async def receive_webhook(source: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    service = MessagingService(db)
    # Background task or direct processing
    # For now, just logging
    await service.process_incoming_message(source, payload)

    return {"status": "received"}
