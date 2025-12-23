from sqlalchemy import Integer, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
from typing import Any

class ServiceConfig(Base):
    __tablename__ = "service_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # 'rag', 'chatwoot', 'espocrm'
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    client = relationship("Client", back_populates="configs")
