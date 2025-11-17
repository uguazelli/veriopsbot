"""Document ingestion pipeline for multi-tenant RAG."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import anyio
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.vector_stores.types import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.vector_stores.postgres import PGVectorStore

try:
    from llama_index.embeddings.openai import OpenAIEmbedding
except ImportError as exc:  # pragma: no cover - dependency missing during import
    raise RuntimeError(
        "OpenAI embedding support requires llama-index-embeddings-openai to be installed."
    ) from exc

try:  # optional dependency; only required when provider=gemini
    from llama_index.embeddings.gemini import GeminiEmbedding
except ImportError:  # pragma: no cover - optional dependency
    GeminiEmbedding = None  # type: ignore

from app.db.connection import resolve_sqlalchemy_urls
from app.db.repository import get_params_by_tenant_id
from app.controller.rag_docs import STORAGE_ROOT


class IngestError(RuntimeError):
    """Raised when ingestion preconditions are not met."""


EMBED_DIMENSIONS: Dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "models/text-embedding-004": 768,  # Gemini text embedding model
}

DEFAULT_EMBED_MODELS: Dict[str, str] = {
    "openai": "text-embedding-3-small",
    "gemini": "models/text-embedding-004",
}

SHARED_VECTOR_TABLE = "rag_vectors"


@dataclass(frozen=True)
class IngestConfig:
    tenant_id: int
    folder_name: str
    provider: str
    api_key: str
    embed_model: str
    table_name: str
    schema_name: str


def _tenant_metadata_filter(tenant_id: int) -> MetadataFilters:
    """Build a PGVector filter that keeps only embeddings for one tenant."""
    return MetadataFilters(
        filters=[
            MetadataFilter(
                key="tenant_id",
                value=str(tenant_id),
                operator=FilterOperator.EQ,
            )
        ]
    )


def _parse_params(raw: object) -> Dict[str, object]:
    """Allow tenant config JSON to be stored as dicts or strings."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise IngestError("Tenant configuration payload contains invalid JSON.") from exc
    return {}


def _docs_directory(folder_name: str) -> Path:
    """Resolve and validate the ingest source folder."""
    folder = STORAGE_ROOT / Path(folder_name).name
    if not folder.exists() or not folder.is_dir():
        raise IngestError(f"Folder '{folder_name}' was not found under {STORAGE_ROOT}.")
    return folder


def _select_embedder(config: IngestConfig):
    """Pick the correct embedding client for the configured provider."""
    provider = config.provider.lower()

    if provider == "openai":
        return OpenAIEmbedding(api_key=config.api_key, model=config.embed_model), config.embed_model

    if provider == "gemini":
        if GeminiEmbedding is None:
            raise IngestError(
                "Gemini provider requested but llama-index Gemini integration is not installed."
            )
        return GeminiEmbedding(api_key=config.api_key, model_name=config.embed_model), config.embed_model

    raise IngestError(f"Embedding provider '{config.provider}' is not supported yet.")


def _embed_dimensions(model_name: str, embedder) -> int:
    """Figure out the embedding width for table creation and validation."""
    if model_name in EMBED_DIMENSIONS:
        return EMBED_DIMENSIONS[model_name]
    sample = embedder.get_text_embedding("dimension probe")
    return len(sample)


def _ingest_sync(config: IngestConfig) -> int:
    """Blocking portion that reads files and upserts them into PGVector."""
    docs_dir = _docs_directory(config.folder_name)

    embedder, embed_model = _select_embedder(config)
    embed_dim = _embed_dimensions(embed_model, embedder)

    documents = SimpleDirectoryReader(str(docs_dir)).load_data()
    if not documents:
        raise IngestError(f"No documents found in folder '{config.folder_name}'.")
    tenant_metadata = _tenant_metadata_filter(config.tenant_id)
    for doc in documents:
        metadata = dict(doc.metadata or {})
        metadata["tenant_id"] = str(config.tenant_id)
        metadata["folder_name"] = config.folder_name
        doc.metadata = metadata

    sync_url, async_url = resolve_sqlalchemy_urls()
    vector_store = PGVectorStore.from_params(
        connection_string=sync_url,
        async_connection_string=async_url,
        table_name=config.table_name,
        schema_name=config.schema_name,
        embed_dim=embed_dim,
        indexed_metadata_keys={("tenant_id", "text")},
    )
    vector_store.delete_nodes(filters=tenant_metadata)

    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        embed_model=embedder,
    )

    return len(documents)


async def ingest_documents(
    tenant_id: int,
    folder_name: str,
    provider: str | None = None,
    *,
    embed_model: str | None = None,
) -> tuple[int, str, str]:
    """Public entry-point used by the API to run an ingest job."""
    tenant_config = await get_params_by_tenant_id(tenant_id)
    if not tenant_config:
        raise IngestError(f"No tenant configuration found for id {tenant_id}.")

    llm_params = _parse_params(tenant_config.get("llm_params"))

    provider_name = (
        provider
        or tenant_config.get("llm_name")
        or llm_params.get("provider")
        or "openai"
    )
    provider_name = str(provider_name).lower()

    api_key = tenant_config.get("llm_api_key") or llm_params.get("api_key")
    if not api_key:
        raise IngestError(f"No API key configured for provider '{provider_name}'.")

    embed_model_name = (
        embed_model
        or llm_params.get("openai_embed_model")
        or llm_params.get("gemini_embed_model")
        or llm_params.get("embed_model")
        or DEFAULT_EMBED_MODELS.get(provider_name)
    )
    if not embed_model_name:
        raise IngestError(
            f"No embedding model configured for provider '{provider_name}'."
        )

    schema_name = llm_params.get("rag_schema_name") or "public"
    table_name = SHARED_VECTOR_TABLE

    config = IngestConfig(
        tenant_id=tenant_id,
        folder_name=folder_name,
        provider=provider_name,
        api_key=str(api_key),
        embed_model=str(embed_model_name),
        table_name=table_name,
        schema_name=str(schema_name),
    )
    ingested = await anyio.to_thread.run_sync(_ingest_sync, config)
    return ingested, provider_name, str(embed_model_name)
