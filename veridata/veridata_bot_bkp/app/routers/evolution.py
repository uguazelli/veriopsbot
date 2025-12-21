from fastapi import APIRouter, Request, HTTPException
from app.services import evolution_service

router = APIRouter()

@router.post("/evolution/webhook")
async def evolution_webhook_post(request: Request):
    payload = await request.json()
    return await evolution_service.process_webhook(payload)

@router.get("/evolution/webhook")
async def evolution_webhook_get():
    return {"message": "The webhook is working"}
