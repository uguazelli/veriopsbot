from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ServiceConfig(Base):
    __tablename__ = "service_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    client = relationship("Client", back_populates="configs")

    def __str__(self):
        return f"{self.platform} Config"


class GlobalConfig(Base):
    __tablename__ = "global_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # updated_at is in the screenshot, so good to map it even if unused
    # updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    # Skipping updated_at for now to avoid datetime imports if not strictly needed for reading.
