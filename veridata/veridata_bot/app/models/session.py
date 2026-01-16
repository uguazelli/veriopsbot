import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class BotSession(Base):
    __tablename__ = "bot_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    external_session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)  # Chatwoot Conversation ID
    rag_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    client = relationship("Client", back_populates="sessions")

    def __str__(self):
        return f"Session {self.external_session_id}"
