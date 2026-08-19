"""FastAPI dependencies for documents module."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, OrgMembership, Role, User
from app.db.session import get_db_session
from app.modules.auth.dependencies import get_auth_service, get_current_user
from app.modules.auth.service import AuthService
from app.modules.documents.service import DocumentsService


async def get_documents_service(session: AsyncSession = Depends(get_db_session)) -> DocumentsService:
    """Get the documents service."""
    return DocumentsService(session)


async def get_current_org_for_documents(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> OrgMembership:
    """Validate that the current user has membership in the requested org.

    Also sets the RLS context variable `app.current_org_id` on the database session.
    """
    membership_data = await auth_service.get_membership(current_user.id, org_id)

    if membership_data is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    org, membership, role = membership_data

    # Set the RLS context variable for this session
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )

    return membership


async def require_document_delete_role(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> OrgMembership:
    """Check if the current user has admin or proposal_manager role in the given org."""
    membership_data = await auth_service.get_membership(current_user.id, org_id)

    if membership_data is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    org, membership, role = membership_data

    allowed_roles = {Role.ADMIN, Role.PROPOSAL_MANAGER}
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of roles: {', '.join(r.value for r in allowed_roles)}",
        )

    # Set the RLS context variable for this session
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )

    return membership


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