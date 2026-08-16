"""Pydantic schemas for jobs module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class JobCreate(BaseModel):
    """Schema for creating a job (dev/test only)."""

    job_type: str = "ping"
    document_id: UUID | None = None


class JobResponse(BaseModel):
    """Schema for job response."""

    id: UUID
    org_id: UUID
    document_id: UUID | None
    job_type: str
    status: str
    current_stage: str | None
    progress_pct: int
    error_message: str | None
    correlation_id: str
    created_at: datetime
    updated_at: datetime