from fastapi import APIRouter, Request
from app.services import chatwoot_service

router = APIRouter()

@router.post("/chatwoot/webhook")
async def chatwoot_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        # Chatwoot might send empty body on verification or errors?
        return {"status": "error", "reason": "invalid_json"}

    return await chatwoot_service.process_webhook(payload)
