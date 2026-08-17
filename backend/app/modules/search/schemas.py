"""Search API schemas."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SearchFilter(BaseModel):
    """Filters for search queries."""

    document_id: Optional[UUID] = None
    document_type: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class SearchRequest(BaseModel):
    """Search request body."""

    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    filters: Optional[SearchFilter] = None
    top_k: int = Field(10, ge=1, le=100, description="Number of results to return")


class SearchResult(BaseModel):
    """Individual search result."""

    chunk_id: UUID
    document_id: UUID
    content: str
    chunk_type: str
    page_start: int
    page_end: int
    section_path: Optional[str] = None
    token_count: int
    filename: str
    document_type: str
    rrf_score: float
    vector_rank: Optional[int] = None
    fulltext_rank: Optional[int] = None


class SearchResponse(BaseModel):
    """Search response."""

    results: list[SearchResult]
    total_results: int
    query: str
