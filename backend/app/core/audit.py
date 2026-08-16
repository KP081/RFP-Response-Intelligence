"""Audit logging core utilities."""

import uuid
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Annotated, Any, Optional, TypeVar

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLogEntry, User
from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user


async def record_audit_event(
    session: AsyncSession,
    org_id: uuid.UUID,
    actor_user_id: Optional[uuid.UUID],
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: dict[str, Any],
    correlation_id: Optional[str] = None,
) -> AuditLogEntry:
    """Record an audit log entry.

    Args:
        session: Database session
        org_id: Organization ID
        actor_user_id: User ID of the actor (None for system events)
        action: Action performed (e.g., "document.upload", "document.download")
        resource_type: Type of resource (e.g., "document", "proposal")
        resource_id: ID of the resource as string
        metadata: Additional metadata about the event
        correlation_id: Optional correlation ID for request tracing

    Returns:
        The created AuditLogEntry
    """
    audit_entry = AuditLogEntry(
        org_id=org_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        event_metadata=metadata,
        correlation_id=correlation_id or str(uuid.uuid4()),
    )
    session.add(audit_entry)
    await session.flush()
    return audit_entry


F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


def audited(
    action: str,
    resource_type: str,
    resource_id_param: str = "document_id",
    metadata_builder: Optional[Callable[[Any], dict[str, Any]]] = None,
) -> Callable[[F], F]:
    """Decorator to automatically audit an endpoint.

    Usage:
        @router.get("/{document_id}/download")
        @audited(action="document.download", resource_type="document")
        async def download_document(...):
            ...

    Args:
        action: The action name to log (e.g., "document.download")
        resource_type: The type of resource (e.g., "document")
        resource_id_param: The path parameter name containing the resource ID
        metadata_builder: Optional callable that takes the response and returns metadata dict
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            org_id: uuid.UUID | None = None
            actor_user_id: uuid.UUID | None = None
            correlation_id: str | None = None

            if request:
                org_id_str = request.path_params.get("org_id")
                if org_id_str:
                    org_id = uuid.UUID(org_id_str)

                if hasattr(request.state, "current_user") and request.state.current_user:
                    actor_user_id = request.state.current_user.id

                correlation_id = request.headers.get("x-correlation-id")

            resource_id: uuid.UUID | str | None = kwargs.get(resource_id_param)
            if resource_id is None and request:
                resource_id = request.path_params.get(resource_id_param)

            response = await func(*args, **kwargs)

            if org_id and actor_user_id and resource_id is not None:
                session: AsyncSession | None = None
                for arg in args:
                    if isinstance(arg, AsyncSession):
                        session = arg
                        break
                if session is None:
                    for kwarg in kwargs.values():
                        if isinstance(kwarg, AsyncSession):
                            session = kwarg
                            break

                if session:
                    metadata: dict[str, Any] = {}
                    if metadata_builder:
                        try:
                            metadata = metadata_builder(response)
                        except Exception:
                            pass

                    # Also check request.state for additional metadata
                    if request and hasattr(request.state, "audit_metadata"):
                        metadata.update(request.state.audit_metadata)

                    await record_audit_event(
                        session=session,
                        org_id=org_id,
                        actor_user_id=actor_user_id,
                        action=action,
                        resource_type=resource_type,
                        resource_id=str(resource_id),
                        metadata=metadata,
                        correlation_id=correlation_id,
                    )

            return response

        return wrapper  # type: ignore[return-value]

    return decorator


async def get_audit_session(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AsyncSession:
    """Dependency that provides a session with audit context set.

    This ensures the session has the RLS context set for the org.
    """
    from app.modules.auth.dependencies import get_auth_service
    from app.modules.auth.service import AuthService

    auth_service: AuthService = await get_auth_service(session)
    membership_data = await auth_service.get_membership(current_user.id, org_id)

    if membership_data is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    from sqlalchemy import text
    await session.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(org_id)},
    )

    return session