"""Service for document operations."""

import uuid
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_object_store
from app.db.models import (
    Document,
    DocumentStatus,
    DocumentType,
    DocumentVersion,
)


class DocumentsService:
    """Service for handling document operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._object_store = get_object_store()

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

        return document

    async def get_document(self, document_id: uuid.UUID, org_id: uuid.UUID) -> Optional[Document]:
        """Get a document by ID, scoped to the given org (defense-in-depth alongside RLS)."""
        stmt = select(Document).where(
            Document.id == document_id,
            Document.org_id == org_id,
            Document.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_document_including_deleted(self, document_id: uuid.UUID, org_id: uuid.UUID) -> Optional[Document]:
        """Get a document by ID including deleted ones (for delete operation), scoped to org."""
        stmt = select(Document).where(
            Document.id == document_id,
            Document.org_id == org_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        org_id: uuid.UUID,
        document_type: Optional[DocumentType] = None,
    ) -> Sequence[Document]:
        """List documents for an organization, optionally filtered by type."""
        stmt = select(Document).where(Document.org_id == org_id, Document.is_deleted.is_(False))
        if document_type:
            stmt = stmt.where(Document.document_type == document_type)
        stmt = stmt.order_by(Document.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def soft_delete_document(self, document_id: uuid.UUID, actor_user_id: uuid.UUID, org_id: uuid.UUID) -> bool:
        """Soft delete a document by setting is_deleted flag, scoped to org."""
        stmt = select(Document).where(
            Document.id == document_id,
            Document.org_id == org_id,
        )
        result = await self.session.execute(stmt)
        document = result.scalar_one_or_none()
        if not document:
            return False

        # Soft delete
        document.is_deleted = True
        await self.session.flush()

        return True