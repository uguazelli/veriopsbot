from fastapi import FastAPI, Request
from app.controller import evolution

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "VeriOps Bot is running"}

@app.post("/evolution/webhook/")
async def evolution_webhook_post(request: Request):
    payload = await request.json()
    return await evolution.process_webhook(payload)

@app.get("/evolution/webhook/")
async def evolution_webhook_get():
    return {"message": "The webhook is working"}
