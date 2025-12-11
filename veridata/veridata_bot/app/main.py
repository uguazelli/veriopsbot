from fastapi import FastAPI, Request
from app.controller import evolution, admin

from app import database
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    yield
    await database.close_db()

app = FastAPI(lifespan=lifespan)
app.include_router(admin.router)

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
