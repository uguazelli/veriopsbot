import asyncio
import os
import uuid
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Use the explicitly found connection details
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://veridata_user:veridata_pass@localhost:5432/veridata_rag")

async def debug():
    print(f"Connecting to {DATABASE_URL}...")
    engine = create_async_engine(DATABASE_URL)

    async with engine.begin() as conn:
        print("\n=== 1. TENANTS ===")
        result = await conn.execute(text("SELECT id, name FROM tenants"))
        tenants = result.fetchall()
        for t in tenants:
            print(f"Tenant: {t.name} ({t.id})")

            # Use SET config just in case RLS is enforced (though we know it's bypassed for owner)
            await conn.execute(
                text("SELECT set_config('app.current_tenant', :id, false)"),
                {"id": str(t.id)}
            )

            print(f"\n   --- Documents for {t.name} ---")
            docs = await conn.execute(text("SELECT id, filename, content FROM documents WHERE tenant_id = :tid ORDER BY filename"), {"tid": t.id})
            rows = docs.fetchall()
            if not rows:
                print("   [NO DOCUMENTS FOUND]")
            for i, d in enumerate(rows):
                if d.filename == 'kb.md':
                    print(f"\n   [CHUNK {i}] content (len={len(d.content)}):")
                    print(d.content)
                    print("-" * 40)

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(debug())
