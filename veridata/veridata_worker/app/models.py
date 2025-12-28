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
