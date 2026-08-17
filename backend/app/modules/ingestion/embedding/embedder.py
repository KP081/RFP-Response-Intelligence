"""Embedding generation for document chunks using the ModelGateway."""

import hashlib
import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.llm.gateway import ModelGateway

logger = structlog.get_logger(__name__)

# Embedding model configuration
EMBEDDING_MODEL_TIER = "fast"
EMBEDDING_BATCH_SIZE = 100
EMBEDDING_DIMENSION = 1536


def _generate_cache_key(content: str) -> str:
    """Generate a deterministic cache key from chunk content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


async def embed_chunks(
    session: AsyncSession,
    org_id: uuid.UUID,
    chunk_ids: list[uuid.UUID],
    model_gateway: ModelGateway,
    correlation_id: str,
) -> dict[str, Any]:
    """
    Generate embeddings for a list of chunks.

    Args:
        session: Database session
        org_id: Organization ID for RLS and cost tracking
        chunk_ids: List of chunk IDs to embed
        model_gateway: ModelGateway instance for LLM calls
        correlation_id: Correlation ID for tracing

    Returns:
        Dictionary with status and count of embedded chunks
    """
    if not chunk_ids:
        return {"status": "success", "embedded_count": 0, "skipped_count": 0}

    # Fetch chunks that need embedding
    stmt = select(Chunk).where(Chunk.id.in_(chunk_ids))
    result = await session.execute(stmt)
    chunks = list(result.scalars().all())

    if not chunks:
        return {"status": "success", "embedded_count": 0, "skipped_count": 0}

    # Process in batches
    embedded_count = 0
    skipped_count = 0

    for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[i : i + EMBEDDING_BATCH_SIZE]

        # Prepare texts and cache keys
        texts = []
        cache_keys = []
        chunk_map = []

        for chunk in batch:
            # Skip if already has embedding
            if chunk.embedding is not None:
                skipped_count += 1
                continue

            texts.append(chunk.content)
            cache_keys.append(_generate_cache_key(chunk.content))
            chunk_map.append(chunk)

        if not texts:
            continue

        # Generate embeddings with individual cache keys per chunk
        # We'll embed the whole batch but cache per chunk
        for j, (text, cache_key, chunk) in enumerate(zip(texts, cache_keys, chunk_map)):
            try:
                # Truncate correlation_id to 36 chars for DB constraint
                chunk_correlation_id = f"{correlation_id}-embed-{chunk.id}"[:36]
                embeddings = await model_gateway.embed(
                    org_id=org_id,
                    task_type="embedding_generation",
                    texts=[text],
                    model_tier=EMBEDDING_MODEL_TIER,
                    cache_key=cache_key,
                    correlation_id=chunk_correlation_id,
                )
                chunk.embedding = embeddings[0]
                embedded_count += 1

            except Exception as e:
                logger.error(
                    "embedding_failed",
                    chunk_id=str(chunk.id),
                    error=str(e),
                )
                raise

        # Commit batch
        await session.commit()
        logger.info(
            "embedding_batch_complete",
            batch_number=i // EMBEDDING_BATCH_SIZE + 1,
            batch_size=len(texts),
            embedded_count=embedded_count,
        )

    return {
        "status": "success",
        "embedded_count": embedded_count,
        "skipped_count": skipped_count,
    }


async def embed_document_chunks(
    session: AsyncSession,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    model_gateway: ModelGateway,
    correlation_id: str,
) -> dict[str, Any]:
    """
    Embed all chunks for a document that don't have embeddings yet.

    Args:
        session: Database session
        org_id: Organization ID
        document_id: Document ID
        model_gateway: ModelGateway instance
        correlation_id: Correlation ID for tracing

    Returns:
        Dictionary with embedding results
    """
    # Get all chunks for this document without embeddings
    stmt = select(Chunk.id).where(
        Chunk.document_id == document_id,
        Chunk.embedding.is_(None),
    )
    result = await session.execute(stmt)
    chunk_ids = list(result.scalars().all())

    if not chunk_ids:
        return {"status": "success", "embedded_count": 0, "skipped_count": 0}

    return await embed_chunks(session, org_id, chunk_ids, model_gateway, correlation_id)
