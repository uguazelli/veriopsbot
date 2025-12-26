import httpx
import logging

logger = logging.getLogger(__name__)

class EspoClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}

    async def sync_lead(self, name: str, email: str = None, phone_number: str = None):
        if not email and not phone_number:
            logger.warning(f"EspoCRM sync matched no email or phone for name: {name}")
            return None # Minimal requirement

        async with httpx.AsyncClient() as client:
            search_url = f"{self.base_url}/api/v1/Lead"

            # 1. Try search by Email
            if email:
                params = {"where[0][type]": "equals", "where[0][attribute]": "emailAddress", "where[0][value]": email}
            elif phone_number:
                # 2. Try search by Phone
                params = {"where[0][type]": "equals", "where[0][attribute]": "phoneNumber", "where[0][value]": phone_number}

            resp = await client.get(search_url, params=params, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()

            if data.get('list'):
                logger.info(f"Found existing lead via {'email' if email else 'phone'}")
                return data['list'][0] # Return existing

            # Create new
            create_url = f"{self.base_url}/api/v1/Lead"

            # Name logic: lastName is usually required. If single word, treat as lastName.
            name_parts = name.strip().split(' ')
            if len(name_parts) > 1:
                first_name = name_parts[0]
                last_name = ' '.join(name_parts[1:])
            else:
                first_name = ""
                last_name = name # Fallback: put full name in last name if single word

            payload = {
                "firstName": first_name,
                "lastName": last_name,
                "status": "New",
                "source": "Call",
                "emailAddress": email,
                "phoneNumber": phone_number
            }
            # Clean empty fields
            payload = {k: v for k, v in payload.items() if v is not None}

            logger.info(f"Creating Lead with payload: {payload}")
            try:
                resp = await client.post(create_url, json=payload, headers=self.headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"EspoCRM Creation Failed: {e.response.text}")
                raise e
            return resp.json()
