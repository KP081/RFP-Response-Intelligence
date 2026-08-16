"""Celery tasks with pipeline job tracking."""

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import structlog
from celery import Task  # type: ignore[import-untyped]
from celery.exceptions import MaxRetriesExceededError  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_object_store
from app.db.models import DocumentStatus, JobStatus, PipelineJob, RawExtraction
from app.db.session import async_session_factory
from app.modules.ingestion.extraction import (
    extract_docx_content,
    extract_pdf_content,
)
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 60


def _get_db_session() -> AsyncSession:
    """Create a new database session for use in tasks."""
    return async_session_factory()


async def _create_pipeline_job(
    session: AsyncSession,
    org_id: uuid.UUID,
    job_type: str,
    correlation_id: str,
    document_id: uuid.UUID | None = None,
) -> PipelineJob:
    """Create a new pipeline job record."""
    job = PipelineJob(
        org_id=org_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        correlation_id=correlation_id,
        document_id=document_id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _update_job_status(
    session: AsyncSession,
    job_id: uuid.UUID,
    status: JobStatus,
    current_stage: str | None = None,
    progress_pct: int | None = None,
    error_message: str | None = None,
) -> None:
    """Update pipeline job status."""
    stmt = select(PipelineJob).where(PipelineJob.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job:
        job.status = status
        if current_stage is not None:
            job.current_stage = current_stage
        if progress_pct is not None:
            job.progress_pct = progress_pct
        if error_message is not None:
            job.error_message = error_message
        await session.commit()


def pipeline_task(
    job_type: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: int = DEFAULT_RETRY_BACKOFF,
) -> Any:
    """Decorator that wraps a Celery task with pipeline job tracking.

    Args:
        job_type: The type identifier for this job (e.g., "ping", "extract_text").
        max_retries: Maximum number of retry attempts (default: 3).
        retry_backoff: Base backoff seconds for exponential retry (default: 60).

    The decorated function must accept these keyword arguments:
        - org_id: UUID of the organization
        - correlation_id: Correlation ID for log tracing
        - document_id: Optional UUID of associated document

    Returns:
        A Celery task that manages pipeline_jobs record lifecycle.
    """

    def decorator(func: Callable[P, Coroutine[Any, Any, R]]) -> Any:
        @celery_app.task(
            bind=True,
            max_retries=max_retries,
            default_retry_delay=retry_backoff,
            autoretry_for=(Exception,),
            retry_backoff=True,
            retry_backoff_max=600,
            retry_jitter=True,
        )
        @wraps(func)
        def wrapper(self: Task, *args: P.args, **kwargs: P.kwargs) -> R:
            org_id: uuid.UUID = kwargs.pop("org_id")  # type: ignore[assignment]
            correlation_id: str = kwargs.pop("correlation_id")  # type: ignore[assignment]
            document_id: uuid.UUID | None = kwargs.pop("document_id", None)  # type: ignore[assignment]

            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(
                correlation_id=correlation_id,
                job_type=job_type,
                task_id=self.request.id,
            )

            async def _run_task() -> R:
                session = _get_db_session()
                try:
                    job = await _create_pipeline_job(
                        session, org_id, job_type, correlation_id, document_id
                    )
                    job_id = job.id

                    await _update_job_status(
                        session, job_id, JobStatus.RUNNING, current_stage=func.__name__, progress_pct=10
                    )

                    logger.info("job_started", job_id=str(job_id), job_type=job_type)

                    result = await func(*args, **kwargs)

                    await _update_job_status(
                        session, job_id, JobStatus.SUCCEEDED, current_stage="completed", progress_pct=100
                    )

                    logger.info("job_succeeded", job_id=str(job_id), job_type=job_type)
                    return result

                except MaxRetriesExceededError:
                    await _update_job_status(
                        session,
                        job_id,
                        JobStatus.FAILED,
                        error_message="Max retries exceeded",
                    )
                    logger.error("job_failed_max_retries", job_id=str(job_id), job_type=job_type)
                    raise
                except Exception as e:
                    try:
                        self.retry(exc=e)
                    except MaxRetriesExceededError:
                        await _update_job_status(
                            session,
                            job_id,
                            JobStatus.FAILED,
                            error_message=str(e)[:5000],
                        )
                        logger.error("job_failed", job_id=str(job_id), job_type=job_type, error=str(e))
                        raise
                    await _update_job_status(
                        session,
                        job_id,
                        JobStatus.RETRYING,
                        error_message=str(e)[:5000],
                    )
                    logger.warning("job_retrying", job_id=str(job_id), job_type=job_type, error=str(e))
                    raise
                finally:
                    await session.close()

            return asyncio.run(_run_task())

        return wrapper

    return decorator


@pipeline_task(job_type="ping", max_retries=3, retry_backoff=10)
async def ping_task(*, org_id: uuid.UUID, correlation_id: str, document_id: uuid.UUID | None = None) -> dict[str, str]:
    """Simple ping task for testing the task queue end-to-end."""
    await asyncio.sleep(1)
    return {"status": "pong", "message": "Task queue is working"}


@pipeline_task(job_type="extract_document_content", max_retries=2, retry_backoff=30)
async def extract_document_content(
    *,
    org_id: uuid.UUID,
    correlation_id: str,
    document_id: uuid.UUID,
) -> dict[str, Any]:
    """
    Extract text and tables from a document.

    This task:
    1. Fetches the document from storage
    2. Routes to appropriate extractor based on mime_type
    3. Runs extraction + header/footer stripping
    4. Persists results to raw_extractions
    5. Updates document status
    """
    from app.db.models import Document, DocumentVersion

    session = _get_db_session()
    object_store = get_object_store()

    try:
        # Get document and version
        doc_stmt = select(Document).where(Document.id == document_id)
        doc_result = await session.execute(doc_stmt)
        document = doc_result.scalar_one_or_none()
        if not document:
            raise ValueError(f"Document {document_id} not found")

        version_stmt = select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.created_at.desc())
        version_result = await session.execute(version_stmt)
        version = version_result.scalar_one_or_none()
        if not version:
            raise ValueError(f"No version found for document {document_id}")

        # Update document status to processing
        document.status = DocumentStatus.PROCESSING
        await session.commit()

        # Download file from storage
        file_data = await object_store.get(version.storage_key)

        # Route to appropriate extractor
        mime_type = document.mime_type
        if mime_type == "application/pdf":
            extractor_name = "pdfplumber"
            blocks = extract_pdf_content(file_data)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            extractor_name = "python-docx"
            blocks = extract_docx_content(file_data)
        else:
            # Unsupported format - mark as failed
            document.status = DocumentStatus.FAILED
            await session.commit()
            error_msg = f"Unsupported mime type: {mime_type}. Needs OCR (not yet supported)."
            logger.error("extraction_failed_unsupported_format", document_id=str(document_id), mime_type=mime_type)
            raise ValueError(error_msg)

        # Persist raw extraction
        raw_extraction = RawExtraction(
            org_id=org_id,
            document_id=document_id,
            version_id=version.id,
            blocks=blocks,
            extractor_used=extractor_name,
        )
        session.add(raw_extraction)

        # Update document status to ready_for_chunking
        document.status = DocumentStatus.READY_FOR_CHUNKING

        await session.commit()

        logger.info(
            "extraction_complete",
            document_id=str(document_id),
            blocks_count=len(blocks),
            extractor=extractor_name,
        )

        return {
            "status": "success",
            "document_id": str(document_id),
            "blocks_count": len(blocks),
            "extractor": extractor_name,
        }

    except Exception:
        # Update document status to failed
        try:
            doc_stmt = select(Document).where(Document.id == document_id)
            doc_result = await session.execute(doc_stmt)
            document = doc_result.scalar_one_or_none()
            if document:
                document.status = DocumentStatus.FAILED
                await session.commit()
        except Exception:
            pass
        raise
    finally:
        await session.close()