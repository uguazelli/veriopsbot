from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    subscriptions = relationship("Subscription", back_populates="client", cascade="all, delete-orphan")
    configs = relationship("ServiceConfig", back_populates="client", cascade="all, delete-orphan")
    sessions = relationship("BotSession", back_populates="client", cascade="all, delete-orphan")

    def __str__(self):
        return f"Client {self.name}"
