from fastapi import APIRouter, Request, HTTPException
from app.services import telegram_service

router = APIRouter()

@router.post("/telegram/webhook/{token}")
async def telegram_webhook_post(token: str, request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    return await telegram_service.process_webhook(token, payload)

@router.get("/telegram/webhook/")
async def telegram_health_check():
    return {"message": "Telegram webhook endpoint is active. POST to /telegram/webhook/{token}"}
