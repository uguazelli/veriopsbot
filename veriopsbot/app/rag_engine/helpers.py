"""Utilities for configuring LLM settings and building retrievers."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.postprocessor.llm_rerank import LLMRerank
from llama_index.core.query_engine.retriever_query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.retrievers.fusion_retriever import QueryFusionRetriever
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.postgres import PGVectorStore

from app.db.connection import resolve_sqlalchemy_urls
from app.db.repository import get_params_by_omnichannel_id

from .ingest import EMBED_DIMENSIONS, SHARED_VECTOR_TABLE

DEFAULT_MODEL_ANSWER = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_K = 4
DEFAULT_MULTI_QUERY = 3
DEFAULT_RERANK_TOP_N = 5
DEFAULT_RETRIEVER_CANDIDATES = 10


def _parse_params(raw: Any) -> Dict[str, Any]:
    """Normalize a JSON-ish payload into a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
    return {}


def _coerce_int(value: Any, default: int) -> int:
    """Best-effort conversion that falls back to a sane default."""
    try:
        parsed = int(float(value))
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    """Float parser that never raises for invalid tenant settings."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def load_runtime_config(account_id: int) -> Dict[str, Any]:
    """Fetch and validate the omnichannel + LLM params for a tenant."""
    config = await get_params_by_omnichannel_id(account_id)
    if not config:
        raise RuntimeError(f"No tenant configuration found for omnichannel id {account_id}")
    return config


def configure_llm_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Populate llama-index global Settings for the tenant's chosen models."""
    llm_params = _parse_params(config.get("llm_params"))
    provider = (config.get("llm_name") or llm_params.get("provider") or "openai").lower()
    api_key = config.get("llm_api_key") or llm_params.get("api_key") or os.getenv("OPENAI_API_KEY")
    if provider != "openai":
        raise RuntimeError(f"Provider '{provider}' is not supported for retrieval yet.")
    if not api_key:
        raise RuntimeError("Missing OpenAI API key in tenant configuration.")

    model_answer = llm_params.get("model_answer") or DEFAULT_MODEL_ANSWER
    temperature = _coerce_float(llm_params.get("temperature"), DEFAULT_TEMPERATURE)
    embed_model = (
        llm_params.get("openai_embed_model")
        or llm_params.get("embed_model")
        or DEFAULT_EMBED_MODEL
    )

    Settings.llm = OpenAI(api_key=api_key, model=model_answer, temperature=temperature)
    Settings.embed_model = OpenAIEmbedding(api_key=api_key, model=embed_model)
    return llm_params


def _resolve_embed_dim(embed_model: str) -> int:
    if embed_model in EMBED_DIMENSIONS:
        return EMBED_DIMENSIONS[embed_model]
    return EMBED_DIMENSIONS.get(DEFAULT_EMBED_MODEL, 1536)


def _tenant_query_customizer(tenant_id: int):
    """Return a SQLAlchemy hook that scopes every vector query to one tenant."""
    def _customize(stmt, table, **kwargs):
        return stmt.where(table.metadata_["tenant_id"].astext == str(tenant_id))

    return _customize


def _vector_store_from_config(
    tenant_id: int,
    llm_params: Dict[str, Any],
    embed_model: str,
) -> PGVectorStore:
    """Instantiate PGVector using the shared table + tenant-specific filters."""
    table_name = SHARED_VECTOR_TABLE
    schema_name = llm_params.get("rag_schema_name") or "public"
    embed_dim = _resolve_embed_dim(embed_model)
    sync_url, async_url = resolve_sqlalchemy_urls()
    return PGVectorStore.from_params(
        connection_string=sync_url,
        async_connection_string=async_url,
        table_name=table_name,
        schema_name=schema_name,
        embed_dim=embed_dim,
        indexed_metadata_keys={("tenant_id", "text")},
        customize_query_fn=_tenant_query_customizer(tenant_id),
    )


async def get_query_engine(
    account_id: int,
    tenant_id: int,
    *,
    runtime_config: Optional[Dict[str, Any]] = None,
    llm_params: Optional[Dict[str, Any]] = None,
) -> RetrieverQueryEngine:
    """Assemble the end-to-end retriever (fusion + rerank + synthesizer)."""
    config = runtime_config or await load_runtime_config(account_id)
    runtime_llm_params = llm_params or configure_llm_from_config(config)

    embed_model = (
        runtime_llm_params.get("openai_embed_model")
        or runtime_llm_params.get("embed_model")
        or DEFAULT_EMBED_MODEL
    )

    vector_store = _vector_store_from_config(tenant_id, runtime_llm_params, embed_model)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        storage_context=storage_context,
    )

    top_k = _coerce_int(runtime_llm_params.get("top_k"), DEFAULT_TOP_K)
    retriever_candidates = _coerce_int(
        runtime_llm_params.get("retriever_candidates"),
        max(DEFAULT_RETRIEVER_CANDIDATES, top_k),
    )
    candidate_pool = max(top_k, retriever_candidates)
    rerank_top_n = _coerce_int(
        runtime_llm_params.get("rerank_top_n"),
        max(DEFAULT_RERANK_TOP_N, min(candidate_pool, top_k)),
    )
    rerank_top_n = min(rerank_top_n, candidate_pool)
    multi_query = _coerce_int(
        runtime_llm_params.get("multi_query_count"),
        DEFAULT_MULTI_QUERY,
    )

    base_retriever = index.as_retriever(similarity_top_k=candidate_pool)
    fusion_retriever = QueryFusionRetriever(
        retrievers=[base_retriever],
        llm=Settings.llm,
        similarity_top_k=candidate_pool,
        num_queries=multi_query,
        verbose=False,
    )

    reranker = LLMRerank(llm=Settings.llm, top_n=rerank_top_n)
    response_synthesizer = get_response_synthesizer(
        llm=Settings.llm,
        response_mode="compact",
    )

    return RetrieverQueryEngine(
        retriever=fusion_retriever,
        node_postprocessors=[reranker],
        response_synthesizer=response_synthesizer,
    )
