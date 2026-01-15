from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

class CalendarProvider(ABC):
    """Abstract Base Class for Calendar Providers."""

    @abstractmethod
    def get_available_slots(
        self, start_date: datetime, end_date: datetime
    ) -> List[datetime]:
        """Returns a list of available start times (UTC)."""
        pass

    @abstractmethod
    def book_slot(
        self,
        start_time: datetime,
        email: str,
        name: Optional[str] = None,
        time_zone: str = "UTC",
    ) -> Optional[str]:
        """Books a slot and returns the confirmation URL or ID."""
        pass
