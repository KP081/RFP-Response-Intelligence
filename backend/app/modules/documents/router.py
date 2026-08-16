"""Documents router for document upload, listing, download, and deletion."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.models import DocumentType, Role, User
from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.documents.dependencies import (
    get_current_org_for_documents,
    get_documents_service,
    get_document,
    require_document_delete_role,
)
from app.modules.documents.schemas import (
    ALLOWED_MIME_TYPES,
    DEFAULT_MAX_FILE_SIZE,
    DocumentDeleteResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentUploadRequest,
    DocumentUploadResponse,
)
from app.modules.documents.service import DocumentsService

router = APIRouter(prefix="/orgs/{org_id}/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    org_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="Document file to upload")],
    document_type: Annotated[DocumentType, Query(description="Type of document")] = DocumentType.OTHER,
    membership: Annotated[User, Depends(get_current_org_for_documents)] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    documents_service: Annotated[DocumentsService, Depends(get_documents_service)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
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
    document = await documents_service.upload_document(
        org_id=org_id,
        user_id=current_user.id,
        filename=file.filename,
        mime_type=file.content_type,
        document_type=document_type,
        file_data=file_data,
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
    membership: Annotated[User, Depends(get_current_org_for_documents)] = None,
    documents_service: Annotated[DocumentsService, Depends(get_documents_service)] = None,
) -> list[DocumentListResponse]:
    """List documents for the organization, optionally filtered by type."""
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
async def get_document(
    org_id: uuid.UUID,
    document: Annotated[DocumentListResponse, Depends(get_document)],
    membership: Annotated[User, Depends(get_current_org_for_documents)] = None,
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


@router.get("/{document_id}/download")
async def download_document(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    membership: Annotated[User, Depends(get_current_org_for_documents)] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    documents_service: Annotated[DocumentsService, Depends(get_documents_service)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> RedirectResponse:
    """Generate a presigned URL and redirect to download the document.

    Does not proxy the file through the API - returns a redirect to the presigned URL.
    """
    from app.core.storage import get_object_store
    from app.db.models import AuditLogEntry

    # Get document (including deleted check)
    document = await documents_service.get_document(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Generate presigned URL
    object_store = get_object_store()
    result = await object_store.get_presigned_url(document.storage_key)

    # Log audit
    audit_entry = AuditLogEntry(
        org_id=org_id,
        actor_user_id=current_user.id,
        action="document.download",
        resource_type="document",
        resource_id=str(document_id),
        event_metadata={"filename": document.filename},
        correlation_id=str(uuid.uuid4()),
    )
    session.add(audit_entry)
    await session.flush()

    return RedirectResponse(url=result.url, status_code=status.HTTP_302_FOUND)


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    membership: Annotated[User, Depends(require_document_delete_role)] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    documents_service: Annotated[DocumentsService, Depends(get_documents_service)] = None,
) -> DocumentDeleteResponse:
    """Soft delete a document (requires admin or proposal_manager role).

    The document is marked as deleted but not physically removed to preserve audit trail.
    """
    success = await documents_service.soft_delete_document(document_id, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return DocumentDeleteResponse(message="Document deleted successfully")