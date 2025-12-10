import logging
from uuid import UUID
from typing import Annotated, Optional
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.db import get_db
from src.auth import get_current_username
from src.rag import ingest_document, generate_answer

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="src/templates")
router = APIRouter()

# Helpers
def get_tenants():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM tenants ORDER BY created_at DESC")
            return cur.fetchall()

def get_tenant_documents(tenant_id: UUID):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, filename, created_at FROM documents WHERE tenant_id = %s ORDER BY created_at DESC", (tenant_id,))
            return cur.fetchall()

# Routes
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, username: str = Depends(get_current_username)):
    tenants = get_tenants()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "tenants": tenants, "selected_tenant": None}
    )

@router.post("/tenants", response_class=HTMLResponse)
async def create_tenant(request: Request, name: Annotated[str, Form()], username: str = Depends(get_current_username)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tenants (name) VALUES (%s) RETURNING id", (name,))
            conn.commit()
    return RedirectResponse(url="/", status_code=303)

@router.get("/tenants/{tenant_id}", response_class=HTMLResponse)
async def view_tenant(request: Request, tenant_id: UUID, username: str = Depends(get_current_username)):
    tenants = get_tenants()
    documents = get_tenant_documents(tenant_id)
    tenant_name = "Unknown"
    for t_id, t_name in tenants:
        if str(t_id) == str(tenant_id):
            tenant_name = t_name
            break

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "tenants": tenants,
            "selected_tenant": {"id": str(tenant_id), "name": tenant_name},
            "documents": documents
        }
    )

@router.post("/ingest", response_class=HTMLResponse)
async def ingest_file(
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    username: str = Depends(get_current_username)
):
    if not file.filename.lower().endswith(('.txt', '.md', '.jpg', '.jpeg', '.png', '.webp')):
        return HTMLResponse('<div class="text-red-500">Supported formats: .txt, .md, .jpg, .png, .webp</div>')

    content = await file.read()
    try:
        # If text, decode it. If image, pass bytes.
        text_content = None
        file_bytes = None

        if file.filename.lower().endswith(('.txt', '.md')):
            text_content = content.decode("utf-8")
        else:
            file_bytes = content

        background_tasks.add_task(ingest_document, tenant_id, file.filename, content=text_content, file_bytes=file_bytes)
        return HTMLResponse(
            f'<div class="text-green-500 mb-2">Started processing {file.filename}... check back soon.</div>'
        )
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return HTMLResponse(f'<div class="text-red-500">Error reading file</div>')

from src.memory import create_session

@router.post("/query", response_class=HTMLResponse)
async def query_rag(
    request: Request,
    tenant_id: Annotated[UUID, Form()],
    query: Annotated[str, Form()],
    use_hyde: Annotated[bool, Form()] = False,
    use_rerank: Annotated[bool, Form()] = False,
    provider: Annotated[str, Form()] = "gemini",
    session_id: Annotated[Optional[str], Form()] = None,
    username: str = Depends(get_current_username)
):
    # Create session if needed
    if not session_id:
        session_id = create_session(tenant_id)

    answer = generate_answer(
        tenant_id,
        query,
        use_hyde=use_hyde,
        use_rerank=use_rerank,
        provider=provider,
        session_id=UUID(session_id)
    )
    return templates.TemplateResponse(
        "partials/chat_response.html",
        {"request": request, "answer": answer, "query": query, "session_id": session_id}
    )

@router.delete("/documents/{doc_id}", response_class=HTMLResponse)
async def delete_document(request: Request, doc_id: UUID, username: str = Depends(get_current_username)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
            conn.commit()
    return HTMLResponse("")
