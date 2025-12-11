import os
import asyncpg
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Construct from components if specific URL not provided
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "postgres")
    DATABASE_URL = f"postgresql://{user}:{password}@{host}:{port}/{db}"

pool: Optional[asyncpg.Pool] = None

async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        await create_tables()
        print("✅ Database connection established and tables checked.")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        # Re-raise to prevent app from starting without DB
        raise e

async def close_db():
    if pool:
        await pool.close()

async def create_tables():
    if not pool:
        return

    async with pool.acquire() as conn:
        # Table for instance -> tenant_id mapping
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mappings (
                instance_name TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL
            );
        """)

        # Table for sessions (memory)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                instance_name TEXT,
                phone_number TEXT,
                session_id TEXT NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (instance_name, phone_number)
            );
        """)

        # Migration: Add is_active if not exists
        try:
            await conn.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;")
        except Exception as e:
            print(f"⚠️ Warning during migration: {e}")

async def get_tenant_id(instance_name: str) -> Optional[str]:
    if not pool:
        return None
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT tenant_id FROM mappings WHERE instance_name = $1",
            instance_name
        )

async def get_all_mappings() -> list[dict]:
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT instance_name, tenant_id FROM mappings ORDER BY instance_name")
        return [dict(row) for row in rows]

async def upsert_mapping(instance_name: str, tenant_id: str):
    if not pool:
        print("❌ ERROR: Connection pool is None in upsert_mapping")
        return
    print(f"🛠️ Upserting mapping: {instance_name} -> {tenant_id}")
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO mappings (instance_name, tenant_id)
            VALUES ($1, $2)
            ON CONFLICT (instance_name) DO UPDATE SET tenant_id = EXCLUDED.tenant_id
        """, instance_name, tenant_id)
    print("✅ Mapping upserted successfully")

async def delete_mapping(instance_name: str):
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM mappings WHERE instance_name = $1", instance_name)

async def get_session_id(instance_name: str, phone_number: str) -> Optional[str]:
    # Returns session_id ONLY if session exists. Status check should be separate or bundled.
    if not pool:
        return None
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT session_id FROM sessions WHERE instance_name = $1 AND phone_number = $2",
            instance_name, phone_number
        )

async def get_session_status(instance_name: str, phone_number: str) -> bool:
    # Returns True if active or if session doesn't exist (default state)
    if not pool:
        return True
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT is_active FROM sessions WHERE instance_name = $1 AND phone_number = $2",
            instance_name, phone_number
        )
        return val if val is not None else True

async def set_session_active(instance_name: str, phone_number: str, is_active: bool):
    if not pool:
        return
    async with pool.acquire() as conn:
        # We need to ensure a row exists to store the preference.
        # If no session_id yet, store a dummy or just ignore?
        # Better to upsert with NULL session_id if possible, or just require a session.
        # But if user says "Stop" as first message, we should respect it.
        # Let's assume we create a placeholder session if needed.
        await conn.execute("""
            INSERT INTO sessions (instance_name, phone_number, session_id, is_active, updated_at)
            VALUES ($1, $2, '', $3, CURRENT_TIMESTAMP)
            ON CONFLICT (instance_name, phone_number)
            DO UPDATE SET is_active = EXCLUDED.is_active, updated_at = CURRENT_TIMESTAMP
        """, instance_name, phone_number, is_active)

async def update_session_id(instance_name: str, phone_number: str, session_id: str):
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO sessions (instance_name, phone_number, session_id, is_active, updated_at)
            VALUES ($1, $2, $3, TRUE, CURRENT_TIMESTAMP)
            ON CONFLICT (instance_name, phone_number)
            DO UPDATE SET session_id = EXCLUDED.session_id, updated_at = CURRENT_TIMESTAMP
        """, instance_name, phone_number, session_id)

async def get_all_sessions() -> list[dict]:
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT instance_name, phone_number, session_id, updated_at, is_active FROM sessions ORDER BY updated_at DESC")
        return [dict(row) for row in rows]

async def delete_session(instance_name: str, phone_number: str):
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM sessions WHERE instance_name = $1 AND phone_number = $2",
            instance_name, phone_number
        )

