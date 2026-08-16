"""Pydantic schemas for documents module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DocumentStatus, DocumentType


class DocumentUploadResponse(BaseModel):
    """Response schema for document upload."""

    id: UUID
    org_id: UUID
    uploaded_by_user_id: UUID
    filename: str
    mime_type: str
    document_type: DocumentType
    status: DocumentStatus
    storage_key: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    """Response schema for document list item."""

    id: UUID
    org_id: UUID
    uploaded_by_user_id: UUID
    filename: str
    mime_type: str
    document_type: DocumentType
    status: DocumentStatus
    storage_key: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentDetailResponse(BaseModel):
    """Response schema for document detail (same as list for now)."""

    id: UUID
    org_id: UUID
    uploaded_by_user_id: UUID
    filename: str
    mime_type: str
    document_type: DocumentType
    status: DocumentStatus
    storage_key: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentDeleteResponse(BaseModel):
    """Response schema for document deletion."""

    message: str


class DocumentUploadRequest(BaseModel):
    """Request schema for document upload (query parameters)."""

    document_type: DocumentType = Field(default=DocumentType.OTHER, description="Type of document")


# Allowed MIME types for upload
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # XLSX
    "image/png",
    "image/jpeg",
}

# Default max file size: 100MB
DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024