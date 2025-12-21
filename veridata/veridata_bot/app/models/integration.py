from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base

class IntegrationConfig(Base):
    __tablename__ = "integration_configs"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, index=True) # chatwoot, espocrm, rag
    settings = Column(JSONB, default={}) # Stores url, api_key, etc.

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True) # Null for global defaults if needed
    client = relationship("Client", back_populates="integrations")
