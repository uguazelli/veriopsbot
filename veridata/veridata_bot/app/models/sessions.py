from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))

    # Platform info (e.g. 'telegram', 'mattermost') + user identifier (e.g. chat_id)
    platform: Mapped[str] = mapped_column(String(50), index=True)
    user_identifier: Mapped[str] = mapped_column(String(100), index=True)

    # The RAG memory ID
    rag_session_id: Mapped[str] = mapped_column(String(100), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    def __repr__(self):
        return f"<ConversationSession(user={self.user_identifier}, rag_session={self.rag_session_id})>"
