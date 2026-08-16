"""Service for document operations."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_object_store
from app.db.models import AuditLogEntry, Document, DocumentStatus, DocumentType, DocumentVersion, OrgMembership, User


class DocumentsService:
    """Service for handling document operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._object_store = get_object_store()

    async def _log_audit(
        self,
        org_id: uuid.UUID,
        actor_user_id: Optional[uuid.UUID],
        action: str,
        resource_type: str,
        resource_id: str,
        metadata: dict[str, object],
    ) -> None:
        """Write an audit log entry."""
        audit_entry = AuditLogEntry(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            event_metadata=metadata,
            correlation_id=str(uuid.uuid4()),
        )
        self.session.add(audit_entry)
        await self.session.flush()

    def _build_storage_key(self, org_id: uuid.UUID, document_id: uuid.UUID, version_id: uuid.UUID, filename: str) -> str:
        """Build the storage key following the convention: {org_id}/{document_id}/{version}/{filename}"""
        return f"{org_id}/{document_id}/{version_id}/{filename}"

    async def upload_document(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        filename: str,
        mime_type: str,
        document_type: DocumentType,
        file_data: bytes,
    ) -> Document:
        """Upload a document to storage and create database records."""
        # Validate file size
        size_bytes = len(file_data)

        # Create document record
        document_id = uuid.uuid4()
        version_id = uuid.uuid4()
        storage_key = self._build_storage_key(org_id, document_id, version_id, filename)

        document = Document(
            id=document_id,
            org_id=org_id,
            uploaded_by_user_id=user_id,
            filename=filename,
            mime_type=mime_type,
            document_type=document_type,
            status=DocumentStatus.UPLOADED,
            storage_key=storage_key,
            size_bytes=size_bytes,
            is_deleted=False,
        )
        self.session.add(document)

        # Create version record
        version = DocumentVersion(
            id=version_id,
            org_id=org_id,
            document_id=document_id,
            storage_key=storage_key,
            size_bytes=size_bytes,
        )
        self.session.add(version)

        # Upload to object storage
        await self._object_store.put(storage_key, file_data, mime_type)

        # Flush to get IDs
        await self.session.flush()

        # Log audit
        await self._log_audit(
            org_id=org_id,
            actor_user_id=user_id,
            action="document.upload",
            resource_type="document",
            resource_id=str(document_id),
            metadata={
                "filename": filename,
                "mime_type": mime_type,
                "document_type": document_type.value,
                "size_bytes": size_bytes,
            },
        )

        return document

    async def get_document(self, document_id: uuid.UUID) -> Optional[Document]:
        """Get a document by ID."""
        stmt = select(Document).where(Document.id == document_id, Document.is_deleted == False)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_document_including_deleted(self, document_id: uuid.UUID) -> Optional[Document]:
        """Get a document by ID including deleted ones (for delete operation)."""
        stmt = select(Document).where(Document.id == document_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        org_id: uuid.UUID,
        document_type: Optional[DocumentType] = None,
    ) -> Sequence[Document]:
        """List documents for an organization, optionally filtered by type."""
        stmt = select(Document).where(Document.org_id == org_id, Document.is_deleted == False)
        if document_type:
            stmt = stmt.where(Document.document_type == document_type)
        stmt = stmt.order_by(Document.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_presigned_download_url(self, document_id: uuid.UUID, expires_in: int = 3600) -> Optional[str]:
        """Get a presigned URL for downloading a document."""
        document = await self.get_document(document_id)
        if not document:
            return None

        result = await self._object_store.get_presigned_url(document.storage_key, expires_in)
        return result.url

    async def soft_delete_document(self, document_id: uuid.UUID, actor_user_id: uuid.UUID) -> bool:
        """Soft delete a document by setting is_deleted flag."""
        document = await self.get_document_including_deleted(document_id)
        if not document:
            return False

        org_id = document.org_id
        document_id_str = str(document_id)
        filename = document.filename

        # Soft delete
        document.is_deleted = True
        await self.session.flush()

        # Log audit
        await self._log_audit(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action="document.delete",
            resource_type="document",
            resource_id=document_id_str,
            metadata={
                "filename": filename,
            },
        )

        return True