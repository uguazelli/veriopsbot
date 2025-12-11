import logging
from uuid import UUID
from typing import List, Dict, Any, Optional
from src.db import get_db

logger = logging.getLogger(__name__)

def create_session(tenant_id: UUID) -> str:
    """Creates a new chat session for a tenant and returns the Session ID."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_sessions (tenant_id) VALUES (%s) RETURNING id",
                (tenant_id,)
            )
            session_id = cur.fetchone()[0]
            conn.commit()
            return str(session_id)

def get_session(session_id: UUID) -> Optional[Dict[str, Any]]:
    """Checks if a session exists."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, tenant_id FROM chat_sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
            if row:
                return {"id": str(row[0]), "tenant_id": str(row[1])}
            return None

def add_message(session_id: UUID, role: str, content: str):
    """Adds a message to the session history."""
    if role not in ('user', 'ai'):
        raise ValueError("Role must be 'user' or 'ai'")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (%s, %s, %s)
                """,
                (session_id, role, content)
            )
            conn.commit()

def get_chat_history(session_id: UUID, limit: int = 10) -> List[Dict[str, str]]:
    """
    Retrieves the most recent chat history for a session.
    Returns list of dicts: [{'role': 'user', 'content': '...'}, ...]
    Ordered oldest to newest (for context window).
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Fetch newest first (LIMIT), then re-order to chronological
            cur.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, limit)
            )
            rows = cur.fetchall()

            # Convert to list of dicts and reverse to chronological order
            history = [{"role": row[0], "content": row[1]} for row in rows]
            return history[::-1]
