import asyncio
import sys
import os

# Adjust path so we can import app modules
sys.path.append(os.getcwd())

from app.core.db import async_session_maker
from app.models.client import Client
from sqlalchemy import select

async def main():
    async with async_session_maker() as session:
        result = await session.execute(select(Client))
        clients = result.scalars().all()
        print(f"Found {len(clients)} clients:")

        print("-" * 30)
        from app.models.config import ServiceConfig
        result = await session.execute(select(ServiceConfig))
        configs = result.scalars().all()
        print(f"Found {len(configs)} configs:")
        for c in configs:
            print(f"ID: {c.id} | ClientID: {c.client_id} | Config Keys: {c.config.keys() if c.config else 'None'}")

if __name__ == "__main__":
    asyncio.run(main())
