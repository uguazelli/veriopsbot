import asyncio
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from app.templates.logs_template import LOGS_HTML

router = APIRouter()

LOG_FILE = "logs/veridata_bot.log"

@router.get("/logs/view", response_class=HTMLResponse)
async def live_logs_page():
    return LOGS_HTML

@router.websocket("/logs/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        if not os.path.exists(LOG_FILE):
             await websocket.send_text(f"Log file not waiting: {LOG_FILE}")
             return

        with open(LOG_FILE, "r") as f:
            try:
                f.seek(0, os.SEEK_END)
                end = f.tell()
                if end > 4096:
                    f.seek(end - 4096)
                else:
                    f.seek(0)
                content = f.read()
                lines = content.splitlines()[-50:]
                for line in lines:
                     await websocket.send_text(line)
            except Exception as e:
                await websocket.send_text(f"Error reading history: {e}")

            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.1)
                    continue
                await websocket.send_text(line.strip())

    except WebSocketDisconnect:
        pass
    except Exception as e:
        pass
