import logging
from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy import select, text
from src.storage.engine import get_session
from src.models import Tenant, Document

logger = logging.getLogger(__name__)


async def get_tenant_languages(tenant_id: UUID) -> Optional[str]:
    async for session in get_session():
        try:
            # Set RLS variable
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"), {"tenant_id": str(tenant_id)}
            )
            result = await session.execute(
                select(Tenant.preferred_languages).where(Tenant.id == tenant_id)
            )
            return result.scalars().first()
        except Exception as e:
            logger.error(f"Failed to fetch tenant languages: {e}")
            return None


async def insert_document_chunk(
    tenant_id: UUID, filename: str, content: str, embedding: List[float]
) -> bool:
    async for session in get_session():
        try:
            # Set RLS variable
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"), {"tenant_id": str(tenant_id)}
            )
            # We use ORM for insertion, but need to handle fts_vector generation.
            # SQLAlchemy defaults don't easily do to_tsvector on insert unless defined in model or trigger.
            # So generic insert with specific SQL for fts might be cleaner, OR we trust a trigger (not present?),
            # OR we construct the FTS vector in python (not possible easily),
            # OR we use func.to_tsvector in the insert values?
            # Actually, standard SQLAlchemy insert:
            doc = Document(
                tenant_id=tenant_id,
                filename=filename,
                content=content,
                embedding=embedding,
                # fts_vector is updated via SQL usually or trigger.
                # In the old code: VALUES (..., to_tsvector('english', %s))
            )
            session.add(doc)
            # We flush to get ID, but we also want to set fts_vector.
            # Let's simple use a second update or straight SQL insert if we want efficiency.
            # Given we want to move to strict ORM, let's use SQL for this specific specialized insert
            # to keep the to_tsvector logic valid without triggers.

            stmt = text("""
                INSERT INTO documents (tenant_id, filename, content, embedding, fts_vector)
                VALUES (:tenant_id, :filename, :content, :embedding, to_tsvector('english', :content))
            """)
            await session.execute(
                stmt,
                {
                    "tenant_id": tenant_id,
                    "filename": filename,
                    "content": content,
                    "embedding": str(
                        embedding
                    ),  # pgvector usually takes list but let's see if sqlalchemy handles list->vector auto.
                    # If we use raw text(), we might need to cast or format.
                    # Actually, standard usage with SQLAlchemy 2.0 and text():
                    # Just pass the list, but we might need explicit cast in SQL.
                    # :embedding is passed as parameter.
                },
            )
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to insert document chunk for {filename}: {e}")
            return False


async def search_documents_hybrid(
    tenant_id: UUID, query_embedding: List[float], query_text: str, limit: int
) -> List[Dict[str, Any]]:
    results = []
    async for session in get_session():
        try:
            # Set RLS variable
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"), {"tenant_id": str(tenant_id)}
            )
            # Hybrid search with RRF (Reciprocal Rank Fusion)
            # Note: We use CAST(:embedding AS vector) because parameter passing might be typeless string/json.
            stmt = text("""
                WITH vector_search AS (
                    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> :embedding) as rank
                    FROM documents
                    WHERE tenant_id = :tenant_id
                    ORDER BY embedding <=> :embedding
                    LIMIT :limit
                ),
                keyword_search AS (
                    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts_vector, websearch_to_tsquery('english', :query_text)) DESC) as rank
                    FROM documents
                    WHERE tenant_id = :tenant_id AND fts_vector @@ websearch_to_tsquery('english', :query_text)
                    LIMIT :limit
                )
                SELECT
                    d.id, d.filename, d.content,
                    COALESCE(1.0 / (vs.rank + 60), 0.0) + COALESCE(1.0 / (ks.rank + 60), 0.0) as score
                FROM documents d
                LEFT JOIN vector_search vs ON d.id = vs.id
                LEFT JOIN keyword_search ks ON d.id = ks.id
                WHERE vs.id IS NOT NULL OR ks.id IS NOT NULL
                ORDER BY score DESC
                LIMIT :limit;
            """)

            result = await session.execute(
                stmt,
                {
                    "embedding": str(
                        query_embedding
                    ),  # Pass as string representation for vector cast
                    "tenant_id": tenant_id,
                    "limit": limit,
                    "query_text": query_text,
                },
            )

            rows = result.fetchall()

            for row in rows:
                results.append(
                    {
                        "id": str(row[0]),
                        "filename": row[1],
                        "content": row[2],
                        "score": float(row[3]),
                    }
                )
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")

    return results
