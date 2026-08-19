"""Celery tasks with pipeline job tracking."""

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import structlog
from celery import Task  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_object_store
from app.db.models import (
    Chunk,
    ChunkType,
    Document,
    DocumentStatus,
    JobStatus,
    PipelineJob,
    PipelineStage,
    PipelineStageStatus,
    RawExtraction,
)
from app.db.session import async_session_factory
from app.llm.gateway import get_model_gateway
from app.modules.ingestion.chunking import create_chunks_from_blocks
from app.modules.ingestion.embedding import embed_document_chunks as embed_chunks_func
from app.modules.ingestion.extraction import (
    extract_docx_content,
    extract_pdf_content,
)
from app.modules.ingestion.pipeline import run_pipeline
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

                except Exception as e:
                    will_retry = self.request.retries < self.max_retries
                    if will_retry:
                        await _update_job_status(
                            session, job_id, JobStatus.RETRYING, error_message=str(e)[:5000]
                        )
                        logger.warning("job_retrying", job_id=str(job_id), job_type=job_type, error=str(e))
                    else:
                        await _update_job_status(
                            session, job_id, JobStatus.FAILED, error_message=str(e)[:5000]
                        )
                        logger.error("job_failed_max_retries", job_id=str(job_id), job_type=job_type)
                    # self.retry() always raises (Retry, or MaxRetriesExceededError if exhausted)
                    # the exception propagates out of this function; `finally` below still runs first.
                    raise self.retry(exc=e)

                finally:
                    await session.close()

            return asyncio.run(_run_task())

        return wrapper

    return decorator


@pipeline_task(job_type="run_ingestion_pipeline", max_retries=2, retry_backoff=60)
async def run_ingestion_pipeline(
    *,
    org_id: uuid.UUID,
    correlation_id: str,
    document_id: uuid.UUID,
    start_from_stage: str | None = None,
) -> dict[str, Any]:
    """
    Run the full document ingestion pipeline.

    This task:
    1. Creates a pipeline job record
    2. Runs the pipeline orchestrator with idempotency checks
    3. Supports resuming from a specific stage (for retry)

    Args:
        org_id: Organization ID
        correlation_id: Correlation ID for tracing
        document_id: Document ID
        start_from_stage: Optional stage name to start from (for retry/resume)

    Returns:
        Dictionary with pipeline execution results
    """
    session = _get_db_session()

    try:
        # Get document
        doc_stmt = select(Document).where(Document.id == document_id)
        doc_result = await session.execute(doc_stmt)
        document = doc_result.scalar_one_or_none()
        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Update document status to processing
        document.status = DocumentStatus.PROCESSING
        await session.commit()

        # Parse start_from_stage if provided
        start_stage = None
        if start_from_stage:
            try:
                start_stage = PipelineStage(start_from_stage)
            except ValueError:
                raise ValueError(f"Invalid start_from_stage: {start_from_stage}")

        # Run pipeline
        results = await run_pipeline(
            session=session,
            org_id=org_id,
            document_id=document_id,
            correlation_id=correlation_id,
            start_from_stage=start_stage,
        )

        # Collect results
        stage_results = []
        for result in results:
            stage_results.append({
                "stage": result.stage.value,
                "status": result.status.value,
                "output": result.output,
                "error": result.error,
            })

        # Check if all stages succeeded
        all_succeeded = all(r.status in (PipelineStageStatus.SUCCEEDED, PipelineStageStatus.SKIPPED) for r in results)

        return {
            "status": "success" if all_succeeded else "failed",
            "document_id": str(document_id),
            "stages": stage_results,
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


@pipeline_task(job_type="retry_ingestion_pipeline", max_retries=2, retry_backoff=60)
async def retry_ingestion_pipeline(
    *,
    org_id: uuid.UUID,
    correlation_id: str,
    document_id: uuid.UUID,
) -> dict[str, Any]:
    """
    Retry a failed document ingestion pipeline from the failed stage.

    This task:
    1. Finds the failed stage from the document's pipeline_stage field
    2. Runs the pipeline from that stage

    Args:
        org_id: Organization ID
        correlation_id: Correlation ID for tracing
        document_id: Document ID

    Returns:
        Dictionary with pipeline execution results
    """
    session = _get_db_session()

    try:
        # Get document
        doc_stmt = select(Document).where(Document.id == document_id)
        doc_result = await session.execute(doc_stmt)
        document = doc_result.scalar_one_or_none()
        if not document:
            raise ValueError(f"Document {document_id} not found")

        if document.pipeline_stage_status != PipelineStageStatus.FAILED:
            raise ValueError(f"Document {document_id} is not in failed state")

        # Get the failed stage
        failed_stage = document.pipeline_stage
        if not failed_stage:
            raise ValueError(f"Document {document_id} has no failed stage")

        # Update document status to processing
        document.status = DocumentStatus.PROCESSING
        document.pipeline_stage_status = PipelineStageStatus.QUEUED
        await session.commit()

        # Run pipeline from failed stage
        results = await run_pipeline(
            session=session,
            org_id=org_id,
            document_id=document_id,
            correlation_id=correlation_id,
            start_from_stage=failed_stage,
        )

        # Collect results
        stage_results = []
        for result in results:
            stage_results.append({
                "stage": result.stage.value,
                "status": result.status.value,
                "output": result.output,
                "error": result.error,
            })

        # Check if all stages succeeded
        all_succeeded = all(r.status in (PipelineStageStatus.SUCCEEDED, PipelineStageStatus.SKIPPED) for r in results)

        return {
            "status": "success" if all_succeeded else "failed",
            "document_id": str(document_id),
            "stages": stage_results,
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


@pipeline_task(job_type="embed_document_chunks", max_retries=2, retry_backoff=30)
async def embed_document_chunks(
    *,
    org_id: uuid.UUID,
    correlation_id: str,
    document_id: uuid.UUID,
) -> dict[str, Any]:
    """
    Embed all chunks for a document.

    This task:
    1. Creates a ModelGateway instance
    2. Embeds all chunks that don't have embeddings yet
    3. Updates document status to READY on success
    """
    from app.db.models import Document, DocumentVersion

    session = _get_db_session()
    model_gateway = get_model_gateway()

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

        # Embed chunks
        result = await embed_chunks_func(
            session=session,
            org_id=org_id,
            document_id=document_id,
            model_gateway=model_gateway,
            correlation_id=correlation_id,
        )

        # Update document status to READY (search-ready state)
        document.status = DocumentStatus.READY
        await session.commit()

        logger.info(
            "embedding_complete",
            document_id=str(document_id),
            embedded_count=result.get("embedded_count", 0),
            skipped_count=result.get("skipped_count", 0),
        )

        return {
            "status": "success",
            "document_id": str(document_id),
            "embedded_count": result.get("embedded_count", 0),
            "skipped_count": result.get("skipped_count", 0),
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


@pipeline_task(job_type="chunk_document", max_retries=2, retry_backoff=30)
async def chunk_document(
    *,
    org_id: uuid.UUID,
    correlation_id: str,
    document_id: uuid.UUID,
) -> dict[str, Any]:
    """
    Chunk a document's raw extractions into retrieval-ready chunks.

    This task:
    1. Reads raw_extractions for the document version
    2. Runs semantic chunking with structure-aware boundaries
    3. Persists chunks to the chunks table
    4. Updates document status
    """
    from app.db.models import Document, DocumentVersion, RawExtraction

    session = _get_db_session()

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

        # Get raw extraction
        extraction_stmt = select(RawExtraction).where(RawExtraction.version_id == version.id)
        extraction_result = await session.execute(extraction_stmt)
        raw_extraction = extraction_result.scalar_one_or_none()
        if not raw_extraction:
            raise ValueError(f"No raw extraction found for version {version.id}")

        blocks = raw_extraction.blocks
        if not blocks:
            raise ValueError("Raw extraction has no blocks")

        # Create chunks
        chunks_data = create_chunks_from_blocks(blocks)

        # Persist chunks
        for chunk_data in chunks_data:
            chunk = Chunk(
                org_id=org_id,
                document_id=document_id,
                version_id=version.id,
                chunk_index=chunk_data["chunk_index"],
                content=chunk_data["content"],
                chunk_type=ChunkType(chunk_data["chunk_type"]),
                page_start=chunk_data["page_start"],
                page_end=chunk_data["page_end"],
                section_path=chunk_data["section_path"],
                token_count=chunk_data["token_count"],
            )
            session.add(chunk)

        # Update document status to ready (for now; full pipeline in task 15)
        document.status = DocumentStatus.READY

        await session.commit()

        # Count by type
        type_counts: dict[str, int] = {}
        for c in chunks_data:
            type_counts[c["chunk_type"]] = type_counts.get(c["chunk_type"], 0) + 1

        logger.info(
            "chunking_complete",
            document_id=str(document_id),
            chunks_count=len(chunks_data),
            type_counts=type_counts,
        )

        return {
            "status": "success",
            "document_id": str(document_id),
            "chunks_count": len(chunks_data),
            "type_counts": type_counts,
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