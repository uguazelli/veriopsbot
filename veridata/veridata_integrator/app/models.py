from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON
import uuid

class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    api_key: str = Field(default_factory=lambda: str(uuid.uuid4()))

    rag_tenant_id: Optional[uuid.UUID] = Field(default=None)
    bot_instance_alias: Optional[str] = Field(default=None)

    sources: List["IntegrationSource"] = Relationship(back_populates="client")
    destinations: List["IntegrationDestination"] = Relationship(back_populates="client")

class IntegrationSource(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id")
    type: str  # evolution, telegram, chatwoot
    config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))

    client: Client = Relationship(back_populates="sources")
    identity_maps: List["IdentityMap"] = Relationship(back_populates="source")

class IntegrationDestination(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id")
    type: str # espocrm
    config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))

    client: Client = Relationship(back_populates="destinations")
    identity_maps: List["IdentityMap"] = Relationship(back_populates="destination")

class IdentityMap(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    source_id: int = Field(foreign_key="integrationsource.id")
    source_user_ref: str # e.g. phone number or telegram ID

    destination_id: int = Field(foreign_key="integrationdestination.id")
    destination_lead_ref: str # e.g. EspoCRM ID

    source: IntegrationSource = Relationship(back_populates="identity_maps")
    destination: IntegrationDestination = Relationship(back_populates="identity_maps")
