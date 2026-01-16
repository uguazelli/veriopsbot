import logging

import httpx

import re
from app.integrations.crm.formatting import ConversationFormatter
from app.bot.utils import extract_contact_info, parse_name

logger = logging.getLogger(__name__)


class EspoClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}

    async def _search_impl(self, client, entity_type, email, phone):
        async def _query(params):
            search_url = f"{self.base_url}/api/v1/{entity_type}"
            resp = await client.get(search_url, params=params, headers=self.headers)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("list"):
                    return data["list"][0]
            return None

        if email:
            params = {"where[0][type]": "equals", "where[0][attribute]": "emailAddress", "where[0][value]": email}
            found = await _query(params)
            if found:
                return found

        if phone:
            params = {"where[0][type]": "equals", "where[0][attribute]": "phoneNumber", "where[0][value]": phone}
            found = await _query(params)
            if found:
                return found

        return None

    async def sync_contact(self, payload: dict):


        info = extract_contact_info(payload)

        email = info["email"]
        phone = info["phone"]
        name = info["name"]

        if not email and not phone:
            logger.warning(f"EspoCRM sync matched no email or phone for name: {name}")
            return None

        async with httpx.AsyncClient() as client:
            contact = await self._search_impl(client, "Contact", email, phone)
            entity_type = "Contact"
            entity_id = contact["id"] if contact else None
            if not entity_id:
                lead = await self._search_impl(client, "Lead", email, phone)
                if lead:
                    entity_type = "Lead"
                    entity_id = lead["id"]

            first_name, last_name = parse_name(name)
            if not last_name:
                last_name = first_name
                first_name = ""

            additional = payload.get("additional_attributes", {})

            payload = {
                "firstName": first_name,
                "lastName": last_name,
                "emailAddress": email,
                "phoneNumber": phone,
                "addressCity": additional.get("city"),
                "addressCountry": additional.get("country"),
                "description": additional.get("description"),
                "accountName": additional.get("company_name"),  # specific for Lead usually
                "title": additional.get("designation") or additional.get("title"),  # sometimes passed
            }

            payload = {k: v for k, v in payload.items() if v}

            if entity_id:
                logger.info(f"Found existing {entity_type}: {entity_id}. Updating...")
                update_url = f"{self.base_url}/api/v1/{entity_type}/{entity_id}"
                try:
                    resp = await client.put(update_url, json=payload, headers=self.headers)
                    resp.raise_for_status()
                    logger.info(f"Updated {entity_type} {entity_id}")
                    return resp.json()
                except httpx.HTTPStatusError as e:
                    logger.error(f"EspoCRM Update Failed: {e.response.text}")
                    raise e
            else:
                logger.info("Creating new Lead")
                create_url = f"{self.base_url}/api/v1/Lead"

                payload["status"] = "New"
                payload["source"] = "Other"

                try:
                    resp = await client.post(create_url, json=payload, headers=self.headers)
                    resp.raise_for_status()
                    logger.info("Created new Lead")
                    return resp.json()
                except httpx.HTTPStatusError as e:
                    logger.error(f"EspoCRM Creation Failed: {e.response.text}")
                    raise e

    async def sync_lead(self, name: str, email: str = None, phone_number: str = None):
        return await self.sync_contact({"name": name, "email": email, "phone_number": phone_number})

    async def update_lead_summary(self, email: str | None, phone: str | None, summary: dict):
        if not email and not phone:
            return

        async with httpx.AsyncClient() as client:
            parent_type = "Lead"
            parent_id = None

            contact = await self._search_impl(client, "Contact", email, phone)
            if contact:
                parent_type = "Contact"
                parent_id = contact["id"]
                logger.info(f"Summary target found: Contact {parent_id}")
            else:
                lead = await self._search_impl(client, "Lead", email, phone)
                if lead:
                    parent_id = lead["id"]
                    logger.info(f"Summary target found: Lead {parent_id}")

            if not parent_id:
                logger.warning(f"Entity not found for summary update: {email or phone}")
                return



            formatter = ConversationFormatter(summary)
            desc = formatter.to_markdown()
            create_note_url = f"{self.base_url}/api/v1/Note"
            payload = {"type": "Post", "post": desc, "parentType": parent_type, "parentId": parent_id}

            logger.info(f"Posting summary to Stream for {parent_type} {parent_id}")
            await client.post(create_note_url, json=payload, headers=self.headers)

            budget = summary.get("detected_budget")
            if budget and parent_type == "Lead":
                try:


                    clean_budget = 0.0
                    if isinstance(budget, (int, float)):
                        clean_budget = float(budget)
                    elif isinstance(budget, str):
                        match = re.search(r"[\d,.]+", budget)
                        if match:
                            clean_str = match.group().replace(",", "")
                            clean_budget = float(clean_str)

                    if clean_budget > 0:
                        update_lead_url = f"{self.base_url}/api/v1/Lead/{parent_id}"
                        lead_payload = {"opportunityAmount": clean_budget, "opportunityAmountCurrency": "USD"}
                        logger.info(f"Updating Lead opportunityAmount to {clean_budget} USD")
                        await client.put(update_lead_url, json=lead_payload, headers=self.headers)

                except Exception as e:
                    logger.warning(f"Failed to update budget for Lead {parent_id}: {e}")
