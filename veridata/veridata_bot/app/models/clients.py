from typing import List, Optional
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import Base

class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    configs: Mapped[List["IntegrationConfig"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Client(name='{self.name}')>"

    def __str__(self):
        return self.name

class IntegrationConfig(Base):
    __tablename__ = "integration_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    platform_name: Mapped[str] = mapped_column(String(50)) # mattermost, telegram, whatsapp, rag, espocrm
    settings: Mapped[dict] = mapped_column(JSONB, default={})

    client: Mapped["Client"] = relationship(back_populates="configs")

    def __repr__(self):
        return f"<IntegrationConfig(platform='{self.platform_name}', client_id={self.client_id})>"

    def __str__(self):
        return f"{self.platform_name} (Client ID: {self.client_id})"
