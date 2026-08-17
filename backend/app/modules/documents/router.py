"""Documents router for document upload, listing, download, and deletion."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audited
from app.core.policy import can_export
from app.db.models import DocumentType, User
from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.documents.dependencies import (
    get_current_org_for_documents,
    get_documents_service,
    require_document_delete_role,
)
from app.modules.documents.dependencies import (
    get_document as get_document_dep,
)
from app.modules.documents.schemas import (
    ALLOWED_MIME_TYPES,
    DEFAULT_MAX_FILE_SIZE,
    DocumentDeleteResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.modules.documents.service import DocumentsService
from app.workers.tasks import run_ingestion_pipeline

router = APIRouter(prefix="/orgs/{org_id}/documents", tags=["documents"])


def upload_metadata_builder(response: DocumentUploadResponse) -> dict[str, Any]:
    """Build metadata for upload audit log."""
    return {
        "filename": response.filename,
        "mime_type": response.mime_type,
        "document_type": response.document_type,
        "size_bytes": response.size_bytes,
    }


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
@audited(
    action="document.upload",
    resource_type="document",
    resource_id_param="id",
    metadata_builder=upload_metadata_builder,
)
async def upload_document(
    org_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="Document file to upload")],
    request: Request,
    document_type: Annotated[DocumentType, Query(description="Type of document")] = DocumentType.OTHER,
    membership: Annotated[User | None, Depends(get_current_org_for_documents)] = None,
    current_user: Annotated[User | None, Depends(get_current_user)] = None,
    documents_service: Annotated[DocumentsService | None, Depends(get_documents_service)] = None,
    session: Annotated[AsyncSession | None, Depends(get_db_session)] = None,
) -> DocumentUploadResponse:
    """Upload a document to the organization.

    Validates MIME type against allowlist and file size limit.
    Streams the upload to object storage and creates database records.
    """
    # Validate MIME type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}. Allowed types: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
        )

    # Read file data
    file_data = await file.read()

    # Validate file size
    if len(file_data) > DEFAULT_MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed size of {DEFAULT_MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    # Validate filename
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    # Upload document
    assert documents_service is not None
    assert current_user is not None
    document = await documents_service.upload_document(
        org_id=org_id,
        user_id=current_user.id,
        filename=file.filename,
        mime_type=file.content_type,
        document_type=document_type,
        file_data=file_data,
    )

    # Enqueue full ingestion pipeline
    correlation_id = f"ingest-{document.id}"
    run_ingestion_pipeline.delay(
        org_id=org_id,
        correlation_id=correlation_id,
        document_id=document.id,
    )

    return DocumentUploadResponse(
        id=document.id,
        org_id=document.org_id,
        uploaded_by_user_id=document.uploaded_by_user_id,
        filename=document.filename,
        mime_type=document.mime_type,
        document_type=document.document_type,
        status=document.status,
        storage_key=document.storage_key,
        size_bytes=document.size_bytes,
        created_at=document.created_at,
    )


@router.get("", response_model=list[DocumentListResponse])
async def list_documents(
    org_id: uuid.UUID,
    document_type: Annotated[DocumentType | None, Query(description="Filter by document type")] = None,
    membership: Annotated[User | None, Depends(get_current_org_for_documents)] = None,
    documents_service: Annotated[DocumentsService | None, Depends(get_documents_service)] = None,
) -> list[DocumentListResponse]:
    """List documents for the organization, optionally filtered by type."""
    assert documents_service is not None
    documents = await documents_service.list_documents(org_id, document_type)

    return [
        DocumentListResponse(
            id=doc.id,
            org_id=doc.org_id,
            uploaded_by_user_id=doc.uploaded_by_user_id,
            filename=doc.filename,
            mime_type=doc.mime_type,
            document_type=doc.document_type,
            status=doc.status,
            storage_key=doc.storage_key,
            size_bytes=doc.size_bytes,
            created_at=doc.created_at,
        )
        for doc in documents
    ]


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_endpoint(
    org_id: uuid.UUID,
    document: Annotated[DocumentListResponse, Depends(get_document_dep)],
    membership: Annotated[User | None, Depends(get_current_org_for_documents)] = None,
) -> DocumentDetailResponse:
    """Get document metadata by ID."""
    return DocumentDetailResponse(
        id=document.id,
        org_id=document.org_id,
        uploaded_by_user_id=document.uploaded_by_user_id,
        filename=document.filename,
        mime_type=document.mime_type,
        document_type=document.document_type,
        status=document.status,
        storage_key=document.storage_key,
        size_bytes=document.size_bytes,
        created_at=document.created_at,
    )


def download_metadata_builder(response: RedirectResponse) -> dict[str, Any]:
    """Build metadata for download audit log - filename extracted from request state."""
    return {}


@router.get("/{document_id}/download")
@audited(
    action="document.download",
    resource_type="document",
    resource_id_param="document_id",
    metadata_builder=download_metadata_builder,
)
async def download_document(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    membership: Annotated[User | None, Depends(get_current_org_for_documents)] = None,
    current_user: Annotated[User | None, Depends(get_current_user)] = None,
    documents_service: Annotated[DocumentsService | None, Depends(get_documents_service)] = None,
    session: Annotated[AsyncSession | None, Depends(get_db_session)] = None,
) -> RedirectResponse:
    """Generate a presigned URL and redirect to download the document.

    Does not proxy the file through the API - returns a redirect to the presigned URL.
    """
    from app.core.storage import get_object_store

    # Get document (including deleted check)
    assert documents_service is not None
    document = await documents_service.get_document(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Check export policy (stub for task 41)
    if not can_export(document):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document export not allowed by policy",
        )

    # Generate presigned URL
    object_store = get_object_store()
    result = await object_store.get_presigned_url(document.storage_key)

    # Store filename in request state for audit metadata
    if request:
        request.state.audit_metadata = {"filename": document.filename}

    return RedirectResponse(url=result.url, status_code=status.HTTP_302_FOUND)


def delete_metadata_builder(response: DocumentDeleteResponse) -> dict[str, Any]:
    """Build metadata for delete audit log."""
    return {}


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
@audited(
    action="document.delete",
    resource_type="document",
    resource_id_param="document_id",
    metadata_builder=delete_metadata_builder,
)
async def delete_document(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    membership: Annotated[User | None, Depends(require_document_delete_role)] = None,
    current_user: Annotated[User | None, Depends(get_current_user)] = None,
    documents_service: Annotated[DocumentsService | None, Depends(get_documents_service)] = None,
) -> DocumentDeleteResponse:
    """Soft delete a document (requires admin or proposal_manager role).

    The document is marked as deleted but not physically removed to preserve audit trail.
    """
    # Get document first for metadata
    assert documents_service is not None
    assert current_user is not None
    document = await documents_service.get_document_including_deleted(document_id)
    if document and request:
        request.state.audit_metadata = {"filename": document.filename}

    success = await documents_service.soft_delete_document(document_id, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return DocumentDeleteResponse(message="Document deleted successfully")