import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add app to path
sys.path.append(str(Path(__file__).parent.parent))

from app.integrations.calendar.factory import get_calendar_provider
from app.integrations.calendar.calcom import CalComProvider

def test_calcom_factory():
    print("Testing Calendar Factory...")

    config = {
        "provider": "calcom",
        "api_key": "cal_live_REPLACE_WITH_REAL_KEY",
        "event_type_id": "123456"
    }

    provider = get_calendar_provider(config)

    if isinstance(provider, CalComProvider):
        print("✅ Factory returned CalComProvider")
    else:
        print(f"❌ Factory returned {type(provider)}")
        return

    print("✅ Api Key:", provider.api_key)
    print("✅ Event Type ID:", provider.event_type_id)

    # Test dummy calls (won't work without real key, but checks Interface)
    try:
        slots = provider.get_available_slots(datetime.utcnow(), datetime.utcnow() + timedelta(days=1))
        print(f"✅ API Call Successful! Found {len(slots)} slots.")
        for slot in slots[:3]:
            print(f"   - {slot}")
    except Exception as e:
        print(f"⚠️ API Call failed: {e}")

if __name__ == "__main__":
    test_calcom_factory()
