"""Search router for hybrid search endpoint."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audited
from app.db.session import get_db_session
from app.llm.gateway import get_model_gateway
from app.modules.auth.dependencies import get_current_user, require_org_member
from app.modules.ingestion.search import hybrid_search
from app.modules.search.schemas import SearchRequest, SearchResponse, SearchResult

router = APIRouter(prefix="/orgs/{org_id}/search", tags=["search"])


def search_metadata_builder(response: SearchResponse) -> dict[str, Any]:
    """Build metadata for search audit log."""
    return {
        "query": response.query,
        "results_count": response.total_results,
    }


@router.post(
    "",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
)
@audited(
    action="search.query",
    resource_type="search",
    resource_id_param="org_id",
    metadata_builder=search_metadata_builder,
)
async def search(
    org_id: uuid.UUID,
    request: Request,
    search_request: SearchRequest,
    membership: Annotated[Any | None, Depends(require_org_member)] = None,
    current_user: Annotated[Any | None, Depends(get_current_user)] = None,
    session: Annotated[AsyncSession | None, Depends(get_db_session)] = None,
) -> SearchResponse:
    """
    Perform hybrid search across document chunks.

    Combines vector similarity search (semantic) with PostgreSQL full-text search
    using Reciprocal Rank Fusion (RRF) for optimal retrieval quality.
    """
    # Build filters dict
    filters: dict[str, Any] = {}
    if search_request.filters:
        if search_request.filters.document_id:
            filters["document_id"] = search_request.filters.document_id
        if search_request.filters.document_type:
            filters["document_type"] = search_request.filters.document_type
        if search_request.filters.date_from:
            filters["date_from"] = search_request.filters.date_from
        if search_request.filters.date_to:
            filters["date_to"] = search_request.filters.date_to

    # Create ModelGateway instance with Redis caching
    model_gateway = get_model_gateway()

    # Perform hybrid search
    if hasattr(request.state, "correlation_id"):
        base_correlation_id = request.state.correlation_id
    else:
        base_correlation_id = uuid.uuid4()
    correlation_id = f"search-{org_id}-{base_correlation_id}"
    results = await hybrid_search(
        org_id=org_id,
        query=search_request.query,
        filters=filters,
        top_k=search_request.top_k,
        model_gateway=model_gateway,
        correlation_id=correlation_id,
    )

    # Convert to response schema
    search_results = [
        SearchResult(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            content=r["content"],
            chunk_type=r["chunk_type"],
            page_start=r["page_start"],
            page_end=r["page_end"],
            section_path=r.get("section_path"),
            token_count=r["token_count"],
            filename=r["filename"],
            document_type=r["document_type"],
            rrf_score=r["rrf_score"],
            vector_rank=r.get("vector_rank"),
            fulltext_rank=r.get("fulltext_rank"),
        )
        for r in results
    ]

    return SearchResponse(
        results=search_results,
        total_results=len(search_results),
        query=search_request.query,
    )

