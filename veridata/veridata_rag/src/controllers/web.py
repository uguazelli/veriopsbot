import logging
import os
import secrets
from uuid import UUID
from typing import Annotated, Optional
from fastapi import (
    APIRouter,
    Request,
    Depends,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, delete, update, func
from src.storage.engine import get_session
from src.models import Tenant, Document
from src.utils.auth import require_auth
from src.services.rag import ingest_document, generate_answer

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="src/templates")
router = APIRouter()


async def get_tenants():
    async for session in get_session():
        result = await session.execute(
            select(Tenant.id, Tenant.name).order_by(Tenant.created_at.desc())
        )
        return result.all()


async def get_tenant_documents(tenant_id: UUID):
    async for session in get_session():
        stmt = (
            select(
                Document.filename,
                func.max(Document.created_at).label("created_at"),
                func.count().label("chunk_count"),
            )
            .where(Document.tenant_id == tenant_id)
            .group_by(Document.filename)
            .order_by(func.max(Document.created_at).desc())
        )
        result = await session.execute(stmt)
        return result.all()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login", response_class=HTMLResponse)
async def login_action(
    request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()]
):
    correct_user = os.getenv("ADMIN_USER", "admin")
    correct_pass = os.getenv("ADMIN_PASSWORD", "admin")
    admin_token = os.getenv("ADMIN_TOKEN", "secret-admin-token")

    if secrets.compare_digest(username, correct_user) and secrets.compare_digest(
        password, correct_pass
    ):
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="session_token", value=admin_token, httponly=True)
        return response

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid username or password"},
        status_code=401,
    )


@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session_token")
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, username: str = Depends(require_auth)):
    tenants = await get_tenants()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "tenants": tenants,
            "selected_tenant": None,
            "username": username,
        },
    )


@router.post("/tenants", response_class=HTMLResponse)
async def create_tenant(
    request: Request,
    name: Annotated[str, Form()],
    username: str = Depends(require_auth),
):
    async for session in get_session():
        tenant = Tenant(name=name)
        session.add(tenant)
        await session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/tenants/{tenant_id}", response_class=HTMLResponse)
async def view_tenant(
    request: Request, tenant_id: UUID, username: str = Depends(require_auth)
):
    tenants = await get_tenants()
    documents = await get_tenant_documents(tenant_id)

    tenant_data = {"id": str(tenant_id), "name": "Unknown", "preferred_languages": ""}

    async for session in get_session():
        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalars().first()
        if tenant:
            tenant_data["name"] = tenant.name
            tenant_data["preferred_languages"] = tenant.preferred_languages or ""

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "tenants": tenants,
            "selected_tenant": tenant_data,
            "documents": documents,
            "username": username,
        },
    )


@router.post("/tenants/{tenant_id}/settings", response_class=HTMLResponse)
async def update_tenant_settings(
    request: Request,
    tenant_id: UUID,
    preferred_languages: Annotated[str, Form()],
    username: str = Depends(require_auth),
):
    async for session in get_session():
        stmt = (
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(preferred_languages=preferred_languages)
        )
        await session.execute(stmt)
        await session.commit()

    return RedirectResponse(url=f"/tenants/{tenant_id}", status_code=303)


@router.post("/ingest", response_class=HTMLResponse)
async def ingest_file(
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    username: str = Depends(require_auth),
):
    if not file.filename.lower().endswith(
        (".txt", ".md", ".jpg", ".jpeg", ".png", ".webp")
    ):
        return HTMLResponse(
            '<div class="text-red-500">Supported formats: .txt, .md, .jpg, .png, .webp</div>'
        )

    content = await file.read()
    try:
        text_content = None
        file_bytes = None

        if file.filename.lower().endswith((".txt", ".md")):
            text_content = content.decode("utf-8")
        else:
            file_bytes = content

        background_tasks.add_task(
            ingest_document,
            tenant_id,
            file.filename,
            content=text_content,
            file_bytes=file_bytes,
        )
        return HTMLResponse(
            f'<div class="text-green-500 mb-2">Started processing {file.filename}... check back soon.</div>'
        )
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return HTMLResponse('<div class="text-red-500">Error reading file</div>')


from src.services.memory import create_session


@router.post("/query", response_class=HTMLResponse)
async def query_rag(
    request: Request,
    tenant_id: Annotated[UUID, Form()],
    query: Annotated[str, Form()],
    use_hyde: Annotated[bool, Form()] = False,
    use_rerank: Annotated[bool, Form()] = False,
    provider: Annotated[str, Form()] = "gemini",
    session_id: Annotated[Optional[str], Form()] = None,
    username: str = Depends(require_auth),
):
    if not session_id:
        session_id = await create_session(tenant_id)

    answer, requires_human = await generate_answer(
        tenant_id,
        query,
        use_hyde=use_hyde,
        use_rerank=use_rerank,
        provider=provider,
        session_id=UUID(session_id),
    )
    return templates.TemplateResponse(
        "partials/chat_response.html",
        {
            "request": request,
            "answer": answer,
            "query": query,
            "session_id": session_id,
        },
    )


@router.delete("/tenants/{tenant_id}/documents", response_class=HTMLResponse)
async def delete_document(
    request: Request,
    tenant_id: UUID,
    filename: str,
    username: str = Depends(require_auth),
):
    async for session in get_session():
        stmt = delete(Document).where(
            Document.tenant_id == tenant_id, Document.filename == filename
        )
        await session.execute(stmt)
        await session.commit()
    return HTMLResponse("")


@router.delete("/tenants/{tenant_id}", response_class=HTMLResponse)
async def delete_tenant(
    request: Request, tenant_id: UUID, username: str = Depends(require_auth)
):
    async for session in get_session():
        stmt = delete(Tenant).where(Tenant.id == tenant_id)
        await session.execute(stmt)
        await session.commit()
    # HX-Redirect tells HTMX to navigate the client to the new URL
    return HTMLResponse("", headers={"HX-Redirect": "/"})
