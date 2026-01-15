from typing import Any, Dict, Optional

from app.integrations.calendar.base import CalendarProvider
from app.integrations.calendar.calcom import CalComProvider

def get_calendar_provider(config: Dict[str, Any]) -> Optional[CalendarProvider]:
    """
    Factory function to return a CalendarProvider instance.

    Expected config structure:
    {
        "provider": "calcom",
        "api_key": "...",
        "event_type_id": "..."
    }
    """
    if not config:
        return None

    provider_type = config.get("provider")

    if provider_type == "calcom":
        api_key = config.get("api_key")
        event_type_id = config.get("event_type_id")
        if api_key and event_type_id:
            return CalComProvider(api_key=api_key, event_type_id=event_type_id)

    # Future: elif provider_type == "calendly": ...

    return None
