from sqlalchemy import Column, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base

class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    slug = Column(String, unique=True, index=True)
    extra_settings = Column(JSONB, nullable=True) # For custom configs

    users = relationship("User", back_populates="client")
    integrations = relationship("IntegrationConfig", back_populates="client")
