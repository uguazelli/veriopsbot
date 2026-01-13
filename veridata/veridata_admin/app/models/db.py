from datetime import datetime
from typing import Optional, List, Dict
import uuid
from sqlalchemy import String, Integer, Boolean, ForeignKey, JSON, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID

class Base(DeclarativeBase):
    pass

class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    sync_configs: Mapped[List["SyncConfig"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    service_configs: Mapped[List["ServiceConfig"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    subscriptions: Mapped[List["Subscription"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    bot_sessions: Mapped[List["BotSession"]] = relationship(back_populates="client", cascade="all, delete-orphan")

    def __str__(self):
        return self.name

class SyncConfig(Base):
    __tablename__ = "sync_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    platform: Mapped[str] = mapped_column(String, index=True)
    config_json: Mapped[dict] = mapped_column(JSON, default={})
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    frequency_minutes: Mapped[int] = mapped_column(Integer, default=60)
    inactivity_threshold_minutes: Mapped[Optional[int]] = mapped_column(Integer, default=30)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    client: Mapped["Client"] = relationship(back_populates="sync_configs")

    def __str__(self):
        return f"{self.platform} ({self.frequency_minutes}m)"

class ServiceConfig(Base):
    __tablename__ = "service_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    config: Mapped[dict] = mapped_column(JSON, default={})

    client: Mapped["Client"] = relationship(back_populates="service_configs")

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    quota_limit: Mapped[int] = mapped_column(Integer, default=1000)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    end_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    client: Mapped["Client"] = relationship(back_populates="subscriptions")

class BotSession(Base):
    __tablename__ = "bot_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    external_session_id: Mapped[str] = mapped_column(String, index=True)
    rag_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    client: Mapped["Client"] = relationship(back_populates="bot_sessions")

class GlobalConfig(Base):
    __tablename__ = "global_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    config: Mapped[dict] = mapped_column(JSON, default={})
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
