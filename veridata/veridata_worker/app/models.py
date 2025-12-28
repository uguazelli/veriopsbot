from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, JSON, Column
from sqlalchemy import BigInteger

class Client(SQLModel, table=True):
    __tablename__ = "clients"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str
    is_active: bool = True

    sync_configs: List["SyncConfig"] = Relationship(back_populates="client")

class SyncConfig(SQLModel, table=True):
    __tablename__ = "sync_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="clients.id")
    platform: str = Field(index=True) # e.g., 'chatwoot', 'espocrm'
    config_json: dict = Field(default={}, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    frequency_minutes: int = Field(default=60)

    client: Optional[Client] = Relationship(back_populates="sync_configs")

class ServiceConfig(SQLModel, table=True):
    """
    Configuration for Bot Service components (RAG, Chatwoot, EspoCRM).
    Shared with veridata_bot.
    """
    __tablename__ = "service_configs"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="clients.id")
    platform: str # 'rag', 'chatwoot', 'espocrm'
    config: dict = Field(default={}, sa_column=Column(JSON))

    client: Optional[Client] = Relationship(sa_relationship_kwargs={"viewonly": True}) # Simplify relationship handling

class Subscription(SQLModel, table=True):
    """
    Quota limits for clients.
    Shared with veridata_bot.
    """
    __tablename__ = "subscriptions"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="clients.id")
    quota_limit: int = Field(default=1000)
    usage_count: int = Field(default=0)
    # Datetime fields skipped for now or need simpler definition for Admin UI if not edited often

    client: Optional[Client] = Relationship(sa_relationship_kwargs={"viewonly": True})

import uuid
from sqlalchemy.dialects.postgresql import UUID

class BotSession(SQLModel, table=True):
    """
    Tracks active bot sessions (Chatwoot <-> RAG).
    Shared with veridata_bot.
    """
    __tablename__ = "bot_sessions"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="clients.id")
    external_session_id: str = Field(index=True) # Chatwoot Conversation ID
    rag_session_id: Optional[uuid.UUID] = Field(default=None, sa_column=Column(UUID(as_uuid=True)))

    client: Optional[Client] = Relationship(sa_relationship_kwargs={"viewonly": True})

