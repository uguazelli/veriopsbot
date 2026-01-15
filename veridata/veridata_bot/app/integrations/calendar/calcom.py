import logging
from datetime import datetime, timedelta
from typing import List, Optional

import httpx

from app.integrations.calendar.base import CalendarProvider

logger = logging.getLogger(__name__)


class CalComProvider(CalendarProvider):
    """Cal.com integration."""

    def __init__(self, api_key: str, event_type_id: str):
        self.api_key = api_key
        self.event_type_id = event_type_id
        self.base_url = "https://api.cal.com/v1"

    def get_available_slots(
        self, start_date: datetime, end_date: datetime
    ) -> List[datetime]:
        """Fetches available slots from Cal.com."""
        # Note: Cal.com API for slots usually requires an eventTypeId or username
        # Endpoint: /slots?startTime=...&endTime=...&eventTypeId=...

        # Ensure dates are ISO strings
        start_str = start_date.isoformat().replace("+00:00", "Z")
        end_str = end_date.isoformat().replace("+00:00", "Z")

        params = {
            "apiKey": self.api_key,
            "startTime": start_str,
            "endTime": end_str,
            "eventTypeId": self.event_type_id,
        }

        try:
            # Note: This is a simplified call. Real Cal.com API usage might need 'username'
            # or different endpoint depending on v1/v2 or self-hosted.
            # Assuming standard v1/slots logic for this provider.
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{self.base_url}/slots", params=params)
                response.raise_for_status()
                data = response.json()

                # Parse response. Structure depends on API version.
                # Common structure: {"slots": {"2024-01-01": [{"time": "..."}]}}
                slots = []
                if "slots" in data:
                    for date_key, day_slots in data["slots"].items():
                        for slot in day_slots:
                            if "time" in slot:
                                dt = datetime.fromisoformat(slot["time"].replace("Z", "+00:00"))
                                slots.append(dt)
                return slots

        except Exception as e:
            logger.error(f"Cal.com get_available_slots failed: {e}")
            return []

    def book_slot(
        self,
        start_time: datetime,
        email: str,
        name: Optional[str] = None,
        time_zone: str = "UTC",
    ) -> Optional[str]:
        """Books an appointment on Cal.com."""
        payload = {
            "eventTypeId": int(self.event_type_id),
            "start": start_time.isoformat().replace("+00:00", "Z"),
            # Cal.com calculates end time based on event type duration usually,
            # but sometimes requires 'end'. Let's assume start is enough or calculate it.
            "responses": {
                "name": name or email.split("@")[0],
                "email": email,
                "location": {"value": "integrations:daily"} # Default to video?
            },
            "timeZone": time_zone,
            "language": "en",
            "metadata": {}
        }

        # For authenticated booking (via API key), we use /bookings
        params = {"apiKey": self.api_key}

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    f"{self.base_url}/bookings", json=payload, params=params
                )
                response.raise_for_status()
                data = response.json()

                # Check for success
                # Return UID or confirmation link
                return f"Booking ID: {data.get('id')} (Check email for link)"

        except Exception as e:
            logger.error(f"Cal.com booking failed: {e}, Response: {response.text if 'response' in locals() else ''}")
            return None
