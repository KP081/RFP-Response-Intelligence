"""Pipeline router for document ingestion pipeline status and events."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import CORRELATION_ID_HEADER
from app.db.models import Document, User
from app.db.session import get_db_session_with_org_id
from app.modules.auth.dependencies import get_current_user
from app.modules.documents.dependencies import get_document as get_document_dep
from app.modules.orgs import require_org_member

router = APIRouter(prefix="/orgs/{org_id}/documents", tags=["documents"])


def get_retry_ingestion_pipeline() -> Any:
    """Lazy dependency for retry ingestion pipeline task to avoid circular imports."""
    from app.workers.tasks import retry_ingestion_pipeline
    return retry_ingestion_pipeline


@router.get("/{document_id}/pipeline-status")
async def get_document_pipeline_status(
    org_id: uuid.UUID,
    document: Annotated[Document, Depends(get_document_dep)],
    membership: Annotated[User, Depends(require_org_member)],
    db_session: Annotated[AsyncSession, Depends(get_db_session_with_org_id)],
) -> dict[str, Any]:
    """Get current pipeline status for a document.

    Returns the current stage, per-stage status, and error detail if failed.
    """
    from app.modules.ingestion.pipeline import get_pipeline_status as get_status

    status_data = await get_status(db_session, document.id)
    return status_data


@router.get("/{document_id}/pipeline-events")
async def stream_pipeline_events(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    membership: Annotated[User, Depends(require_org_member)],
    db_session: Annotated[AsyncSession, Depends(get_db_session_with_org_id)],
) -> StreamingResponse:
    """Stream pipeline events via Server-Sent Events (SSE).

    This endpoint streams stage-transition events in real-time.
    The client should reconnect automatically on disconnect.
    """
    # Verify document exists and belongs to org
    stmt = select(Document).where(Document.id == document_id, Document.org_id == org_id)
    result = await db_session.execute(stmt)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events."""
        last_stage = None
        last_status = None
        last_error = None

        # Send initial status
        from app.modules.ingestion.pipeline import get_pipeline_status as get_status
        initial_status = await get_status(db_session, document_id)

        yield f"data: {initial_status}\n\n"

        # Poll for changes
        while True:
            if await request.is_disconnected():
                break

            try:
                current_status = await get_status(db_session, document_id)

                # Check for changes
                current_stage = current_status.get("current_stage")
                current_pipeline_status = current_status.get("status")

                if (current_stage != last_stage or
                    current_pipeline_status != last_status or
                    current_status.get("stages", {}).get(current_stage, {}).get("error") != last_error):

                    yield f"data: {current_status}\n\n"
                    last_stage = current_stage
                    last_status = current_pipeline_status
                    last_error = current_status.get("stages", {}).get(current_stage, {}).get("error")

                # If pipeline is complete or failed, send final event and stop
                if current_pipeline_status in ("ready", "failed"):
                    yield f"data: {current_status}\n\n"
                    break

            except Exception as e:
                # Log error but continue polling
                import structlog
                logger = structlog.get_logger(__name__)
                logger.error("sse_poll_error", document_id=str(document_id), error=str(e))

            await asyncio.sleep(1)  # Poll every second

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/{document_id}/pipeline-retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_document_pipeline(
    org_id: uuid.UUID,
    document: Annotated[Document, Depends(get_document_dep)],
    membership: Annotated[User, Depends(require_org_member)],
    current_user: Annotated[User, Depends(get_current_user)],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session_with_org_id)],
) -> dict[str, str]:
    """Retry a failed document ingestion pipeline from the failed stage.

    This endpoint re-triggers the pipeline from the stage that failed,
    skipping already-completed stages (idempotent).
    """
    if document.pipeline_stage_status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document is not in failed state (current: {document.pipeline_stage_status})",
        )

    correlation_id = request.headers.get(CORRELATION_ID_HEADER, str(uuid.uuid4()))

    # Enqueue retry task
    get_retry_ingestion_pipeline().delay(
        org_id=org_id,
        correlation_id=correlation_id,
        document_id=document.id,
    )

    return {"status": "retry_queued", "correlation_id": correlation_id}