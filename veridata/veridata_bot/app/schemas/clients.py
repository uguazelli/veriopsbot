from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Any

class ClientBase(BaseModel):
    name: str = Field(..., max_length=100)
    slug: str = Field(..., max_length=50)

class ClientCreate(ClientBase):
    pass

class ClientRead(ClientBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class IntegrationConfigBase(BaseModel):
    client_id: int
    platform_name: str = Field(..., max_length=50)
    settings: dict[str, Any] = Field(default_factory=dict)

class IntegrationConfigCreate(IntegrationConfigBase):
    pass

class IntegrationConfigRead(IntegrationConfigBase):
    id: int
    model_config = ConfigDict(from_attributes=True)
