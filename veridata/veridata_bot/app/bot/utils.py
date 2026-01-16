from typing import Any, Dict, Optional, Tuple


def extract_contact_info(payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
    email = payload.get("email")
    phone = payload.get("phone_number") or payload.get("phone")
    name = payload.get("name")

    if not email and not phone:
        contact = payload.get("contact")
        if isinstance(contact, dict):
            email = contact.get("email")
            phone = contact.get("phone_number") or contact.get("phone")
            name = contact.get("name")

    if not email and not phone:
        sender = payload.get("sender") or payload.get("meta", {}).get("sender")
        if isinstance(sender, dict):
            email = sender.get("email")
            phone = sender.get("phone_number") or sender.get("phone")
            name = sender.get("name")

    return {"email": email, "phone": phone, "name": name or "Unknown"}


def parse_name(full_name: str) -> Tuple[str, str]:
    if not full_name:
        return "", ""

    parts = full_name.strip().split(" ", 1)
    first_name = parts[0]

    if len(parts) > 1:
        last_name = parts[1]
    else:
        last_name = ""

    return first_name, last_name
