import logging
from uuid import UUID
from typing import List, Dict, Any, Optional
from sqlalchemy import select, delete
from src.storage.engine import get_session
from src.models import ChatSession, ChatMessage

logger = logging.getLogger(__name__)


async def create_session(tenant_id: UUID) -> str:
    async for session in get_session():
        try:
            new_session = ChatSession(tenant_id=tenant_id)
            session.add(new_session)
            await session.commit()
            await session.refresh(new_session)
            return str(new_session.id)
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise


async def get_session_data(session_id: UUID) -> Optional[Dict[str, Any]]:
    async for session in get_session():
        result = await session.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        chat_session = result.scalars().first()
        if chat_session:
            return {
                "id": str(chat_session.id),
                "tenant_id": str(chat_session.tenant_id),
            }
        return None


async def add_message(session_id: UUID, role: str, content: str):
    if role not in ("user", "ai"):
        raise ValueError("Role must be 'user' or 'ai'")

    async for session in get_session():
        try:
            msg = ChatMessage(session_id=session_id, role=role, content=content)
            session.add(msg)
            await session.commit()
        except Exception as e:
            logger.error(f"Failed to add message: {e}")
            raise


async def get_chat_history(session_id: UUID, limit: int = 10) -> List[Dict[str, str]]:
    async for session in get_session():
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        # rows are in DESC order (newest first). We reverse to get chronological order.
        history = [{"role": msg.role, "content": msg.content} for msg in rows]
        return history[::-1]


async def get_full_chat_history(session_id: UUID) -> List[Dict[str, str]]:
    async for session in get_session():
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in rows
        ]


async def delete_session(session_id: UUID):
    async for session in get_session():
        try:
            # Cascading delete is handled by database, but we can be explicit if needed.
            # ORM cascade is safer.
            # But here we just delete the session, FK cascade carries the messages.
            stmt = delete(ChatSession).where(ChatSession.id == session_id)
            await session.execute(stmt)
            await session.commit()
            logger.info(f"Deleted session {session_id} and its history.")
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            raise
