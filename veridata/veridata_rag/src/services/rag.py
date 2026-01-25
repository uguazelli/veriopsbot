import logging
from typing import Optional
from uuid import UUID
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from src.config.logging import log_start, log_skip
from src.storage.repository import insert_document_chunk
from src.services.vlm import describe_image
from src.utils.prompts import RAG_ANSWER_PROMPT_TEMPLATE, SMALL_TALK_PROMPT_TEMPLATE
from src.services.rag_flow import (
    get_embed_model,
    resolve_config,
    get_language_instruction,
    prepare_query_context,
    determine_intent,
    retrieve_context,
    generate_llm_response,
    generate_llm_response,
    save_interaction,
)
from src.services.config_service import get_rag_global_config

logger = logging.getLogger(__name__)


# ==================================================================================
# INGESTION FLOW
# 1. Parse Input: Handle text or image (file_bytes -> VLM description).
# 2. Document Creation: Wrap content in LlamaIndex Document.
# 3. Chunking: Split large text into manageable nodes (1024 tokens).
# 4. Embedding: Convert chunks to vectors using Gemini.
# 5. Storage: Insert text + vectors into Postgres (via Repository).
# ==================================================================================
async def ingest_document(
    tenant_id: UUID, filename: str, content: str = None, file_bytes: bytes = None
):
    logger.info(f"Ingesting document {filename} for tenant {tenant_id}")

    is_image = filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))

    if is_image:
        if not file_bytes:
            logger.error("Image ingestion requires file_bytes")
            return
        logger.info("Processing image with VLM...")

        # Fetch dynamic config to get model_name
        config = await get_rag_global_config()
        db_model_name = config.get("model_name")

        # Overwrite content with the image description
        content = describe_image(file_bytes, filename, model_name=db_model_name)
        # We can prepend a tag so we know it's an image description
        content = f"[IMAGE DESCRIPTION for {filename}]\n{content}"

    if not content:
        logger.warning(f"No content to ingest for {filename}")
        return

    # 1. Create LlamaIndex Document
    doc = Document(
        text=content,
        metadata={
            "filename": filename,
            "tenant_id": str(tenant_id),
            "original_type": "image" if is_image else "text",
        },
    )

    # 2. Chunking
    splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=20)
    nodes = splitter.get_nodes_from_documents([doc])

    logger.info(f"Split into {len(nodes)} chunks")

    # 3. Embedding
    embed_model = get_embed_model()
    texts = [node.get_content() for node in nodes]

    try:
        embeddings = embed_model.get_text_embedding_batch(texts)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return

    # 4. Insert into DB (Delegated to Repository)
    for node, embedding in zip(nodes, embeddings):
        success = await insert_document_chunk(
            tenant_id, filename, node.get_content(), embedding
        )
        if not success:
            logger.error(f"Failed to insert chunk for {filename}")

    logger.info(f"Successfully ingested {filename}")


# ==================================================================================
# GENERATION ORCHESTRATOR
# The "Main Loop" of RAG.
# 1. Setup: Load tenant preferences (Language).
# 2. Contextualize: Rewrite user query based on chat history.
# 3. Intent: Decide Complexity (Small Talk vs RAG) & Routing (Fast vs Reasoner Model).
# 4. Retrieve: Search Vectors + Hybrid Search + Rerank.
# 5. Generate: Feed Context + Query to LLM.
# 6. Save: Persist the conversation.
# ==================================================================================
async def generate_answer(
    tenant_id: UUID,
    query: str,
    use_hyde: Optional[bool] = None,
    use_rerank: Optional[bool] = None,
    provider: Optional[str] = None,
    session_id: Optional[UUID] = None,
    complexity_score: int = 5,
    pricing_intent: bool = False,
    external_context: Optional[str] = None,
) -> tuple[str, str]:
    log_start(logger, f"Generating answer for query: '{query}'")

    # 0. Load Dynamic Config (DB Override)
    config = await get_rag_global_config()
    db_model_name = config.get("model_name")

    # Resolving flags: DB > Request > Default
    db_use_hyde = config.get("use_hyde")
    db_use_rerank = config.get("use_rerank")

    if use_hyde is None:
        use_hyde = db_use_hyde
    if use_rerank is None:
        use_rerank = db_use_rerank

    # 1. Config Resolving (Fallback to env/default)
    use_hyde, use_rerank = resolve_config(use_hyde, use_rerank)
    lang_instruction = await get_language_instruction(tenant_id)

    # 2. Contextualization
    search_query, history = await prepare_query_context(session_id, query, provider, model_name=db_model_name)
    history_str = (
        "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])
        if history
        else ""
    )

    # 3. Intent & Routing
    requires_rag, gen_step = determine_intent(complexity_score, pricing_intent)

    # 4. Execution Flow
    answer = ""
    if requires_rag:
        # Retrieve docs & Generate Answer
        context_str, final_lang_instruction = await retrieve_context(
            tenant_id,
            search_query,
            external_context,
            use_hyde,
            use_rerank,
            provider,
            lang_instruction,
            model_name=db_model_name,
        )
        answer = generate_llm_response(
            prompt_template=RAG_ANSWER_PROMPT_TEMPLATE,
            template_args={
                "lang_instruction": final_lang_instruction,
                "history_str": history_str,
                "context_str": context_str,
                "search_query": search_query,
            },
            gen_step=gen_step,
            provider=provider,
            model_name=db_model_name,
        )
    else:
        # Small Talk (No RAG)
        log_skip(logger, "Small talk detected. Bypassing RAG.")
        answer = generate_llm_response(
            prompt_template=SMALL_TALK_PROMPT_TEMPLATE,
            template_args={
                "lang_instruction": lang_instruction,
                "history_str": history_str,
                "search_query": search_query,
            },
            gen_step=gen_step,
            provider=provider,
            model_name=db_model_name,
        )

    # 5. Persistence
    await save_interaction(session_id, query, answer)

    # Return (Answer, Context)
    # Handoff Detection removed (handled by Bot Agent Tool Call)
    return answer, context_str if requires_rag else ""
