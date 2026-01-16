from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    quota_limit: Mapped[int] = mapped_column(Integer, default=1000)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    client = relationship("Client", back_populates="subscriptions")

    def __str__(self):
        return f"Subscription(Limit={self.quota_limit}, Usage={self.usage_count})"
