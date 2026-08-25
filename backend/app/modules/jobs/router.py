"""Jobs router for async task queue management."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import CORRELATION_ID_HEADER
from app.db.models import OrgMembership, PipelineJob
from app.db.session import async_session_factory, get_db_session_with_org_id
from app.modules.auth.dependencies import get_current_user, require_org_member
from app.modules.jobs.schemas import JobCreate, JobResponse
from app.workers.tasks import ping_task

router = APIRouter(prefix="/orgs/{org_id}/jobs", tags=["jobs"])


@router.post("/ping", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_ping_job(
    org_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(require_org_member)],
    current_user: Annotated[uuid.UUID, Depends(get_current_user)],
    request: Request,
    job_data: JobCreate | None = None,
) -> JobResponse:
    """Create a ping job for testing the task queue (dev/test only).

    This endpoint enqueues a simple ping task that demonstrates the full
    job lifecycle: queued -> running -> succeeded.
    """
    correlation_id = request.headers.get(CORRELATION_ID_HEADER, str(uuid.uuid4()))
    document_id = job_data.document_id if job_data else None

    _ = ping_task.apply_async(
        kwargs={
            "org_id": org_id,
            "correlation_id": correlation_id,
            "document_id": document_id,
        }
    )

    async with async_session_factory() as db_session:
        await db_session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )
        stmt = select(PipelineJob).where(PipelineJob.correlation_id == correlation_id)
        result = await db_session.execute(stmt)
        job = result.scalar_one_or_none()
        if job:
            return JobResponse(
                id=job.id,
                org_id=job.org_id,
                document_id=job.document_id,
                job_type=job.job_type,
                status=job.status.value,
                current_stage=job.current_stage,
                progress_pct=job.progress_pct,
                error_message=job.error_message,
                correlation_id=job.correlation_id,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Job not found after creation")


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    org_id: uuid.UUID,
    job_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(require_org_member)],
    db_session: Annotated[AsyncSession, Depends(get_db_session_with_org_id)],
) -> JobResponse:
    """Get current status of a pipeline job.

    This endpoint is used for polling job progress until task 15 adds SSE streaming.
    """
    stmt = select(PipelineJob).where(PipelineJob.id == job_id, PipelineJob.org_id == org_id)
    result = await db_session.execute(stmt)
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    return JobResponse(
        id=job.id,
        org_id=job.org_id,
        document_id=job.document_id,
        job_type=job.job_type,
        status=job.status.value,
        current_stage=job.current_stage,
        progress_pct=job.progress_pct,
        error_message=job.error_message,
        correlation_id=job.correlation_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )