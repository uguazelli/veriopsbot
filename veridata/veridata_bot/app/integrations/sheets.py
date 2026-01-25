import csv
import logging
from io import StringIO

import httpx

logger = logging.getLogger(__name__)


async def fetch_google_sheet_data(url: str, query: str = None) -> str:
    try:
        if "/edit" in url:
            url = url.split("/edit")[0] + "/export?format=csv"
        elif "/view" in url:
            url = url.split("/view")[0] + "/export?format=csv"

        logger.info(f"🌐 Fetching live data from: {url}")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

            f = StringIO(response.text)
            reader = csv.DictReader(f)

            items = []
            rows_processed = 0
            for row in reader:
                rows_processed += 1
                name = row.get("Product Name") or row.get("item_name")
                price = row.get("Price") or row.get("item_price")
                sku = row.get("ID / SKU") or row.get("item_id")
                item_desc = row.get("Description (AI Context)") or row.get("item_desc") or ""
                ai_notes = row.get("AI Notes (Hidden Rules)") or row.get("context") or ""

                # --- Filtering Logic ---
                if query:
                    # Basic case-insensitive keyword match
                    query_lower = query.lower()
                    # Check name, description, SKU
                    search_target = f"{name} {item_desc} {sku} {ai_notes}".lower()
                    if query_lower not in search_target:
                        continue
                # -----------------------

                # Combine description and hidden rules
                full_context = []
                if item_desc: full_context.append(f"Desc: {item_desc}")
                if ai_notes: full_context.append(f"Rules: {ai_notes}")
                context_str = " | ".join(full_context)

                if name:
                    items.append(f"* {name} ({sku}): {price} | {context_str}")

            logger.info(f"📋 Sheet processing complete. Filter: '{query or 'ALL'}'. Rows: {rows_processed}, Matches: {len(items)}")

            if not items:
                if query:
                    return f"No products found matching '{query}'."
                logger.warning("Empty items list after processing CSV.")
                return ""

            # Simple truncation for safety if filtering returns too many
            if len(items) > 50:
                 return f"[TOO MANY RESULTS] Found {len(items)} items matching '{query}'. Please be more specific."

            res = "\n[LIVE PRICING & PRODUCT DATA]\n" + "\n".join(items) + "\n(Source: Live Google Sheet)\n\n"
            logger.info(f"DEBUG: Pricing Data being sent to Agent:\n{res}")
            return res
    except Exception as e:
        logger.error(f"Failed to fetch Google Sheet: {e}")
        return ""
