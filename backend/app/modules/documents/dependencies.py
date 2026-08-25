"""FastAPI dependencies for documents module."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, OrgMembership, Role
from app.db.session import get_db_session
from app.modules.auth.dependencies import (
    require_org_member as get_current_org_for_documents,
)
from app.modules.auth.dependencies import (
    require_org_role,
)
from app.modules.documents.service import DocumentsService


async def get_documents_service(session: AsyncSession = Depends(get_db_session)) -> DocumentsService:
    """Get the documents service."""
    return DocumentsService(session)


# Thin alias for OpenAPI clarity - document delete requires admin or proposal_manager
require_document_delete_role = require_org_role(Role.ADMIN, Role.PROPOSAL_MANAGER)


async def get_document(
    document_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(get_current_org_for_documents)],
    documents_service: Annotated[DocumentsService, Depends(get_documents_service)],
) -> Document:
    """Get a document by ID, ensuring it belongs to the current org."""
    document = await documents_service.get_document(document_id, membership.org_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return document