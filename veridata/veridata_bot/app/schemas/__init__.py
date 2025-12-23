from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Dict, Any
import uuid

# Client Schemas
class ClientBase(BaseModel):
    name: str
    slug: str
    is_active: bool = True

class ClientCreate(ClientBase):
    pass

class ClientUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    is_active: Optional[bool] = None

class ClientRead(ClientBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# Subscription Schemas
class SubscriptionBase(BaseModel):
    client_id: int
    quota_limit: int = 1000
    usage_count: int = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class SubscriptionCreate(SubscriptionBase):
    pass

class SubscriptionUpdate(BaseModel):
    quota_limit: Optional[int] = None
    usage_count: Optional[int] = None
    end_date: Optional[datetime] = None

class SubscriptionRead(SubscriptionBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# Application Config Schemas
class ServiceConfigBase(BaseModel):
    client_id: int
    platform: str
    config: Dict[str, Any]

class ServiceConfigCreate(ServiceConfigBase):
    pass

class ServiceConfigUpdate(BaseModel):
    platform: Optional[str] = None
    config: Optional[Dict[str, Any]] = None

class ServiceConfigRead(ServiceConfigBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# BotSession Schemas
class BotSessionBase(BaseModel):
    client_id: int
    external_session_id: str
    rag_session_id: Optional[uuid.UUID] = None

class BotSessionCreate(BotSessionBase):
    pass

class BotSessionUpdate(BaseModel):
    rag_session_id: Optional[uuid.UUID] = None

class BotSessionRead(BotSessionBase):
    id: int
    model_config = ConfigDict(from_attributes=True)
