import httpx
import logging

logger = logging.getLogger(__name__)

class EspoClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}

    async def _search_impl(self, client, entity_type, email, phone):
        search_url = f"{self.base_url}/api/v1/{entity_type}"
        params = {}
        if email:
            params = {"where[0][type]": "equals", "where[0][attribute]": "emailAddress", "where[0][value]": email}
        elif phone:
            params = {"where[0][type]": "equals", "where[0][attribute]": "phoneNumber", "where[0][value]": phone}

        if not params: return None

        resp = await client.get(search_url, params=params, headers=self.headers)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('list'):
                return data['list'][0]
        return None

    async def sync_lead(self, name: str, email: str = None, phone_number: str = None):
        if not email and not phone_number:
            logger.warning(f"EspoCRM sync matched no email or phone for name: {name}")
            return None # Minimal requirement

        async with httpx.AsyncClient() as client:
            # 1. Check Contact first (Converted/Active Client)
            contact = await self._search_impl(client, "Contact", email, phone_number)
            if contact:
                logger.info(f"Found existing Contact: {contact['id']}")
                return contact

            # 2. Check Lead
            lead = await self._search_impl(client, "Lead", email, phone_number)
            if lead:
                logger.info(f"Found existing Lead: {lead['id']}")
                return lead

            # 3. Create New Lead
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
                "source": "Web Site",
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

    async def update_lead_summary(self, email: str | None, phone: str | None, summary: dict):
        if not email and not phone:
            return

        async with httpx.AsyncClient() as client:
            parent_type = "Lead"
            parent_id = None

            # 1. Search Contact (Priority)
            contact = await self._search_impl(client, "Contact", email, phone)
            if contact:
                parent_type = "Contact"
                parent_id = contact['id']
                logger.info(f"Summary target found: Contact {parent_id}")
            else:
                # 2. Search Lead
                lead = await self._search_impl(client, "Lead", email, phone)
                if lead:
                    parent_id = lead['id']
                    logger.info(f"Summary target found: Lead {parent_id}")

            if not parent_id:
                logger.warning(f"Entity not found for summary update: {email or phone}")
                return

            # 3. Format Description
            desc = (
                f"### AI Conversation Summary 🤖\n\n"
                f"**Period**: {summary.get('conversation_start', 'N/A')} - {summary.get('conversation_end', 'N/A')}\n"
                f"**Summary**: {summary.get('ai_summary', 'N/A')}\n\n"
                f"**Client Profile**: {summary.get('client_description', 'N/A')}\n"
                f"**Analysis**:\n"
                f"- Intent: {summary.get('purchase_intent')}\n"
                f"- Urgency: {summary.get('urgency_level')}\n"
                f"- Sentiment: {summary.get('sentiment_score')}\n"
                f"- Budget: {summary.get('detected_budget')}\n"
            )

            # 4. Post to Stream (Create Note)
            create_note_url = f"{self.base_url}/api/v1/Note"
            payload = {
                "type": "Post",
                "post": desc,
                "parentType": parent_type,
                "parentId": parent_id
            }

            logger.info(f"Posting summary to Stream for {parent_type} {parent_id}")
            await client.post(create_note_url, json=payload, headers=self.headers)

            # 5. Update Budget (Opportunity Amount) if detected
            budget = summary.get('detected_budget')

            if budget and parent_type == "Lead":
                try:
                    # Simple parsing: remove non-numeric chars except dot/comma
                    import re
                    clean_budget = 0.0
                    if isinstance(budget, (int, float)):
                        clean_budget = float(budget)
                    elif isinstance(budget, str):
                        # Extract first valid number
                        match = re.search(r'[\d,.]+', budget)
                        if match:
                            clean_str = match.group().replace(',', '') # rudimentary parsing
                            clean_budget = float(clean_str)

                    if clean_budget > 0:
                        update_lead_url = f"{self.base_url}/api/v1/Lead/{parent_id}"
                        lead_payload = {
                            "opportunityAmount": clean_budget,
                            "opportunityAmountCurrency": "USD" # Fix for validation failure
                        }
                        logger.info(f"Updating Lead opportunityAmount to {clean_budget} USD")
                        await client.put(update_lead_url, json=lead_payload, headers=self.headers)

                except Exception as e:
                    logger.warning(f"Failed to update budget for Lead {parent_id}: {e}")
