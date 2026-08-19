"""Hybrid search combining vector similarity and full-text search with reciprocal rank fusion."""

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.gateway import ModelGateway, get_model_gateway

logger = structlog.get_logger(__name__)

# RRF constant (k parameter)
RRF_K = 60
# Number of results to fetch from each search method before fusion
SEARCH_TOP_N = 50


async def generate_query_embedding(
    query: str,
    org_id: uuid.UUID,
    model_gateway: ModelGateway,
    correlation_id: str,
) -> list[float]:
    """Generate embedding for a search query."""
    embeddings = await model_gateway.embed(
        org_id=org_id,
        task_type="search_query_embedding",
        texts=[query],
        model_tier="fast",
        correlation_id=correlation_id,
    )
    return embeddings[0]


def _build_filters_where_clause(filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build WHERE clause and parameters from filters."""
    conditions = []
    params = {}

    if "document_id" in filters and filters["document_id"]:
        conditions.append("c.document_id = :document_id")
        params["document_id"] = filters["document_id"]

    if "document_type" in filters and filters["document_type"]:
        conditions.append("d.document_type = :document_type")
        params["document_type"] = filters["document_type"]

    if "date_from" in filters and filters["date_from"]:
        conditions.append("d.created_at >= :date_from")
        params["date_from"] = filters["date_from"]

    if "date_to" in filters and filters["date_to"]:
        conditions.append("d.created_at <= :date_to")
        params["date_to"] = filters["date_to"]

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    return where_clause, params


async def _vector_search(
    session: AsyncSession,
    org_id: uuid.UUID,
    query_embedding: list[float],
    filters: dict[str, Any],
    top_k: int,
) -> list[dict[str, Any]]:
    """Perform vector similarity search using cosine distance."""
    where_clause, filter_params = _build_filters_where_clause(filters)

    # Format embedding for pgvector
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    query = text(f"""
        SELECT
            c.id,
            c.document_id,
            c.content,
            c.chunk_type,
            c.page_start,
            c.page_end,
            c.section_path,
            c.token_count,
            c.embedding <-> :embedding AS distance,
            d.filename,
            d.document_type
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE c.org_id = :org_id
        AND c.embedding IS NOT NULL
        AND {where_clause}
        ORDER BY c.embedding <-> :embedding
        LIMIT :top_k
    """)

    params = {
        "org_id": org_id,
        "embedding": embedding_str,
        "top_k": top_k,
        **filter_params,
    }

    result = await session.execute(query, params)
    rows = result.mappings().all()

    return [
        {
            "chunk_id": row["id"],
            "document_id": row["document_id"],
            "content": row["content"],
            "chunk_type": row["chunk_type"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "section_path": row["section_path"],
            "token_count": row["token_count"],
            "distance": float(row["distance"]),
            "filename": row["filename"],
            "document_type": row["document_type"],
            "score": 1.0 - float(row["distance"]),  # Convert distance to similarity
        }
        for row in rows
    ]


async def _fulltext_search(
    session: AsyncSession,
    org_id: uuid.UUID,
    query: str,
    filters: dict[str, Any],
    top_k: int,
) -> list[dict[str, Any]]:
    """Perform full-text search using PostgreSQL's tsvector/tsquery."""
    where_clause, filter_params = _build_filters_where_clause(filters)

    # Parse query into tsquery (plainto_tsquery for simple queries)
    sql_query = text(f"""
        SELECT
            c.id,
            c.document_id,
            c.content,
            c.chunk_type,
            c.page_start,
            c.page_end,
            c.section_path,
            c.token_count,
            ts_rank(c.search_vector, plainto_tsquery('english', :query)) AS rank,
            d.filename,
            d.document_type
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE c.org_id = :org_id
        AND c.search_vector @@ plainto_tsquery('english', :query)
        AND {where_clause}
        ORDER BY rank DESC
        LIMIT :top_k
    """)

    params = {
        "org_id": org_id,
        "query": query,
        "top_k": top_k,
        **filter_params,
    }

    result = await session.execute(sql_query, params)
    rows = result.mappings().all()

    return [
        {
            "chunk_id": row["id"],
            "document_id": row["document_id"],
            "content": row["content"],
            "chunk_type": row["chunk_type"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "section_path": row["section_path"],
            "token_count": row["token_count"],
            "rank": float(row["rank"]),
            "filename": row["filename"],
            "document_type": row["document_type"],
            "score": float(row["rank"]),
        }
        for row in rows
    ]


def _reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    fulltext_results: list[dict[str, Any]],
    top_k: int,
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    """
    Fuse results using Reciprocal Rank Fusion (RRF).

    RRF score = sum(1 / (k + rank)) for each result list
    where rank is 1-based position in the result list.
    """
    # Build rank maps
    vector_ranks = {r["chunk_id"]: i + 1 for i, r in enumerate(vector_results)}
    fulltext_ranks = {r["chunk_id"]: i + 1 for i, r in enumerate(fulltext_results)}

    # Collect all unique chunk IDs
    all_chunk_ids = set(vector_ranks.keys()) | set(fulltext_ranks.keys())

    # Calculate RRF scores
    fused_results = []
    for chunk_id in all_chunk_ids:
        score = 0.0
        if chunk_id in vector_ranks:
            score += 1.0 / (k + vector_ranks[chunk_id])
        if chunk_id in fulltext_ranks:
            score += 1.0 / (k + fulltext_ranks[chunk_id])

        # Get the full result object (prefer vector result for metadata)
        result_obj = None
        for r in vector_results:
            if r["chunk_id"] == chunk_id:
                result_obj = r.copy()
                break
        if result_obj is None:
            for r in fulltext_results:
                if r["chunk_id"] == chunk_id:
                    result_obj = r.copy()
                    break

        if result_obj:
            result_obj["rrf_score"] = score
            result_obj["vector_rank"] = vector_ranks.get(chunk_id)
            result_obj["fulltext_rank"] = fulltext_ranks.get(chunk_id)
            fused_results.append(result_obj)

    # Sort by RRF score descending
    fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)

    return fused_results[:top_k]


async def hybrid_search(
    org_id: uuid.UUID,
    query: str,
    filters: dict[str, Any] | None = None,
    top_k: int = 10,
    model_gateway: ModelGateway | None = None,
    correlation_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Perform hybrid search combining vector similarity and full-text search.

    Args:
        org_id: Organization ID (for RLS)
        query: Search query string
        filters: Optional filters (document_id, document_type, date_from, date_to)
        top_k: Number of results to return
        model_gateway: ModelGateway instance (created if not provided)
        correlation_id: Optional correlation ID for tracing

    Returns:
        List of search results with fused scores, ranked by relevance
    """
    if filters is None:
        filters = {}

    if model_gateway is None:
        model_gateway = get_model_gateway()

    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    logger.info(
        "hybrid_search_started",
        org_id=str(org_id),
        query=query,
        filters=filters,
        top_k=top_k,
        correlation_id=correlation_id,
    )

    session = None
    try:
        from sqlalchemy import text

        from app.db.session import async_session_factory

        session = async_session_factory()

        # Set RLS context for this session
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )

        # Generate query embedding
        embed_correlation_id = f"{correlation_id}-embed"[:36]
        query_embedding = await generate_query_embedding(
            query=query,
            org_id=org_id,
            model_gateway=model_gateway,
            correlation_id=embed_correlation_id,
        )

        # Run both searches in parallel-ish (sequential for now)
        vector_results = await _vector_search(
            session=session,
            org_id=org_id,
            query_embedding=query_embedding,
            filters=filters,
            top_k=SEARCH_TOP_N,
        )

        fulltext_results = await _fulltext_search(
            session=session,
            org_id=org_id,
            query=query,
            filters=filters,
            top_k=SEARCH_TOP_N,
        )

        # Fuse results using RRF
        fused_results = _reciprocal_rank_fusion(
            vector_results=vector_results,
            fulltext_results=fulltext_results,
            top_k=top_k,
        )

        logger.info(
            "hybrid_search_complete",
            org_id=str(org_id),
            query=query,
            vector_results=len(vector_results),
            fulltext_results=len(fulltext_results),
            fused_results=len(fused_results),
            correlation_id=correlation_id,
        )

        return fused_results

    finally:
        if session:
            await session.close()
