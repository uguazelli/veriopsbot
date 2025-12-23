import httpx

class EspoClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}

    async def sync_lead(self, name: str, email: str = None):
        if not email:
            return None # Minimal requirement

        async with httpx.AsyncClient() as client:
            # Check if exists
            search_url = f"{self.base_url}/api/v1/Lead"
            params = {"where[0][type]": "equals", "where[0][attribute]": "emailAddress", "where[0][value]": email}

            resp = await client.get(search_url, params=params, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()

            if data.get('list'):
                return data['list'][0] # Return existing

            # Create new
            create_url = f"{self.base_url}/api/v1/Lead"
            payload = {
                "firstName": name.split(' ')[0],
                "lastName": ' '.join(name.split(' ')[1:]) if ' ' in name else '',
                "emailAddress": email
            }
            resp = await client.post(create_url, json=payload, headers=self.headers)
            resp.raise_for_status()
            return resp.json()
