"""Pipeline orchestrator for document ingestion.

Defines the canonical linear pipeline with stage registration, idempotency checks,
and per-stage retry/resume capability.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Chunk,
    Document,
    DocumentStatus,
    DocumentVersion,
    JobStatus,
    PipelineJob,
    PipelineStage,
    PipelineStageStatus,
    RawExtraction,
)

logger = structlog.get_logger(__name__)


@dataclass
class StageDefinition:
    """Definition of a pipeline stage."""

    name: PipelineStage
    display_name: str
    handler: Callable[..., Awaitable[dict[str, Any]]]
    is_conditional: bool = False
    condition: Callable[..., Awaitable[bool]] | None = None
    idempotency_check: Callable[..., Awaitable[bool]] | None = None


@dataclass
class StageResult:
    """Result of a stage execution."""

    stage: PipelineStage
    status: PipelineStageStatus
    output: dict[str, Any] | None = None
    error: str | None = None


class StageHandler(ABC):
    """Abstract base for stage handlers."""

    @abstractmethod
    async def execute(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Execute the stage logic."""
        pass

    @abstractmethod
    async def is_complete(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> bool:
        """Check if stage output already exists (idempotency)."""
        pass


class ExtractStageHandler(StageHandler):
    """Extract text and tables from document."""

    async def execute(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        from app.core.storage import get_object_store
        from app.modules.ingestion.extraction import (
            extract_docx_content,
            extract_pdf_content,
        )

        # Get document and version
        doc_stmt = select(Document).where(Document.id == document_id)
        doc_result = await session.execute(doc_stmt)
        document = doc_result.scalar_one_or_none()
        if not document:
            raise ValueError(f"Document {document_id} not found")

        version_stmt = select(DocumentVersion).where(DocumentVersion.id == version_id)
        version_result = await session.execute(version_stmt)
        version = version_result.scalar_one_or_none()
        if not version:
            raise ValueError(f"Version {version_id} not found")

        object_store = get_object_store()
        file_data = await object_store.get(version.storage_key)

        mime_type = document.mime_type
        if mime_type == "application/pdf":
            extractor_name = "pdfplumber"
            blocks = extract_pdf_content(file_data)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            extractor_name = "python-docx"
            blocks = extract_docx_content(file_data)
        else:
            document.status = DocumentStatus.FAILED
            await session.commit()
            error_msg = f"Unsupported mime type: {mime_type}. Needs OCR (not yet supported)."
            logger.error("extraction_failed_unsupported_format", document_id=str(document_id), mime_type=mime_type)
            raise ValueError(error_msg)

        # Persist raw extraction
        raw_extraction = RawExtraction(
            org_id=org_id,
            document_id=document_id,
            version_id=version_id,
            blocks=blocks,
            extractor_used=extractor_name,
        )
        session.add(raw_extraction)
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

    async def is_complete(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> bool:
        stmt = select(RawExtraction).where(
            RawExtraction.document_id == document_id,
            RawExtraction.version_id == version_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


class ChunkStageHandler(StageHandler):
    """Chunk raw extractions into retrieval-ready chunks."""

    async def execute(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        from app.db.models import ChunkType
        from app.modules.ingestion.chunking import create_chunks_from_blocks

        # Get raw extraction
        extraction_stmt = select(RawExtraction).where(RawExtraction.version_id == version_id)
        extraction_result = await session.execute(extraction_stmt)
        raw_extraction = extraction_result.scalar_one_or_none()
        if not raw_extraction:
            raise ValueError(f"No raw extraction found for version {version_id}")

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
                version_id=version_id,
                chunk_index=chunk_data["chunk_index"],
                content=chunk_data["content"],
                chunk_type=ChunkType(chunk_data["chunk_type"]),
                page_start=chunk_data["page_start"],
                page_end=chunk_data["page_end"],
                section_path=chunk_data["section_path"],
                token_count=chunk_data["token_count"],
            )
            session.add(chunk)

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

    async def is_complete(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> bool:
        stmt = select(Chunk).where(
            Chunk.document_id == document_id,
            Chunk.version_id == version_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


class EmbedStageHandler(StageHandler):
    """Generate embeddings for document chunks."""

    async def execute(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        from app.llm.gateway import get_model_gateway
        from app.modules.ingestion.embedding import embed_document_chunks as embed_chunks_func

        model_gateway = get_model_gateway()

        result = await embed_chunks_func(
            session=session,
            org_id=org_id,
            document_id=document_id,
            model_gateway=model_gateway,
            correlation_id=correlation_id,
        )

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

    async def is_complete(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> bool:
        stmt = select(Chunk).where(
            Chunk.document_id == document_id,
            Chunk.version_id == version_id,
            Chunk.embedding.is_not(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


class OcrStageHandler(StageHandler):
    """OCR stage (placeholder for task 16)."""

    async def execute(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        # Placeholder - task 16 will implement
        logger.warning("ocr_stage_not_implemented", document_id=str(document_id))
        return {"status": "skipped", "reason": "OCR not yet implemented"}

    async def is_complete(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> bool:
        return True  # Always complete (skipped) for now


class CaptionFiguresStageHandler(StageHandler):
    """Caption figures stage (placeholder for task 17)."""

    async def execute(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        # Placeholder - task 17 will implement
        logger.warning("caption_figures_stage_not_implemented", document_id=str(document_id))
        return {"status": "skipped", "reason": "Caption figures not yet implemented"}

    async def is_complete(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> bool:
        return True  # Always complete (skipped) for now


class DedupeStageHandler(StageHandler):
    """Dedupe stage (placeholder for task 18)."""

    async def execute(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        correlation_id: str,
    ) -> dict[str, Any]:
        # Placeholder - task 18 will implement
        logger.warning("dedupe_stage_not_implemented", document_id=str(document_id))
        return {"status": "skipped", "reason": "Dedupe not yet implemented"}

    async def is_complete(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> bool:
        return True  # Always complete (skipped) for now


# Stage registry - ordered list of stages
STAGE_HANDLERS: dict[PipelineStage, StageHandler] = {
    PipelineStage.EXTRACT: ExtractStageHandler(),
    PipelineStage.CHUNK: ChunkStageHandler(),
    PipelineStage.EMBED: EmbedStageHandler(),
    PipelineStage.OCR: OcrStageHandler(),
    PipelineStage.CAPTION_FIGURES: CaptionFiguresStageHandler(),
    PipelineStage.DEDUPE: DedupeStageHandler(),
}

# Default pipeline order (linear with conditional stages)
DEFAULT_PIPELINE_ORDER = [
    PipelineStage.EXTRACT,
    PipelineStage.CHUNK,
    PipelineStage.EMBED,
    PipelineStage.OCR,
    PipelineStage.CAPTION_FIGURES,
    PipelineStage.DEDUPE,
]


async def get_latest_version(session: AsyncSession, document_id: uuid.UUID) -> DocumentVersion | None:
    """Get the latest version for a document."""
    stmt = select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.created_at.desc())
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def run_pipeline(
    session: AsyncSession,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    correlation_id: str,
    pipeline_job_id: uuid.UUID | None = None,
    start_from_stage: PipelineStage | None = None,
) -> list[StageResult]:
    """
    Run the document ingestion pipeline.

    Args:
        session: Database session
        org_id: Organization ID
        document_id: Document ID
        correlation_id: Correlation ID for tracing
        pipeline_job_id: Optional pipeline job ID for status updates
        start_from_stage: Optional stage to start from (for retry/resume)

    Returns:
        List of stage results
    """
    # Get document
    doc_stmt = select(Document).where(Document.id == document_id)
    doc_result = await session.execute(doc_stmt)
    document = doc_result.scalar_one_or_none()
    if not document:
        raise ValueError(f"Document {document_id} not found")

    # Get latest version
    version = await get_latest_version(session, document_id)
    if not version:
        raise ValueError(f"No version found for document {document_id}")

    version_id = version.id
    results: list[StageResult] = []

    # Determine which stages to run
    stages_to_run = DEFAULT_PIPELINE_ORDER
    if start_from_stage:
        try:
            start_idx = stages_to_run.index(start_from_stage)
            stages_to_run = stages_to_run[start_idx:]
        except ValueError:
            raise ValueError(f"Invalid start stage: {start_from_stage}")

    for stage in stages_to_run:
        handler = STAGE_HANDLERS.get(stage)
        if not handler:
            logger.warning("no_handler_for_stage", stage=stage.value)
            results.append(StageResult(stage=stage, status=PipelineStageStatus.SKIPPED, error="No handler registered"))
            continue

        # Check if stage is already complete (idempotency)
        is_complete = await handler.is_complete(session, document_id, version_id)
        if is_complete and stage != start_from_stage:
            logger.info("stage_already_complete_skipping", stage=stage.value, document_id=str(document_id))
            results.append(StageResult(stage=stage, status=PipelineStageStatus.SKIPPED, output={"skipped": True}))
            continue

        # Update pipeline job status
        if pipeline_job_id:
            job_stmt = select(PipelineJob).where(PipelineJob.id == pipeline_job_id)
            job_result = await session.execute(job_stmt)
            job = job_result.scalar_one_or_none()
            if job:
                job.current_stage = stage.value
                job.status = JobStatus.RUNNING
                # Calculate progress
                stage_idx = DEFAULT_PIPELINE_ORDER.index(stage)
                total_stages = len(DEFAULT_PIPELINE_ORDER)
                job.progress_pct = int((stage_idx / total_stages) * 100)
                await session.commit()

        # Execute stage
        try:
            logger.info("stage_started", stage=stage.value, document_id=str(document_id))

            # Update document pipeline stage
            document.pipeline_stage = stage
            document.pipeline_stage_status = PipelineStageStatus.RUNNING
            document.status = DocumentStatus.PROCESSING
            await session.commit()

            output = await handler.execute(session, org_id, document_id, version_id, correlation_id)

            results.append(StageResult(stage=stage, status=PipelineStageStatus.SUCCEEDED, output=output))

            # Update document pipeline stage
            document.pipeline_stage_status = PipelineStageStatus.SUCCEEDED
            await session.commit()

            # Update pipeline job
            if pipeline_job_id:
                job_stmt = select(PipelineJob).where(PipelineJob.id == pipeline_job_id)
                job_result = await session.execute(job_stmt)
                job = job_result.scalar_one_or_none()
                if job:
                    job.current_stage = stage.value
                    job.status = JobStatus.RUNNING
                    stage_idx = DEFAULT_PIPELINE_ORDER.index(stage)
                    total_stages = len(DEFAULT_PIPELINE_ORDER)
                    job.progress_pct = int(((stage_idx + 1) / total_stages) * 100)
                    await session.commit()

        except Exception as e:
            logger.error("stage_failed", stage=stage.value, document_id=str(document_id), error=str(e))
            results.append(StageResult(stage=stage, status=PipelineStageStatus.FAILED, error=str(e)))

            # Update document pipeline stage
            document.pipeline_stage = stage
            document.pipeline_stage_status = PipelineStageStatus.FAILED
            document.status = DocumentStatus.FAILED
            await session.commit()

            # Update pipeline job
            if pipeline_job_id:
                job_stmt = select(PipelineJob).where(PipelineJob.id == pipeline_job_id)
                job_result = await session.execute(job_stmt)
                job = job_result.scalar_one_or_none()
                if job:
                    job.current_stage = stage.value
                    job.status = JobStatus.FAILED
                    job.error_message = str(e)[:5000]
                    await session.commit()

            break

    # If all stages succeeded, mark document as ready
    all_succeeded = all(r.status in (PipelineStageStatus.SUCCEEDED, PipelineStageStatus.SKIPPED) for r in results)
    if all_succeeded:
        document.status = DocumentStatus.READY
        document.pipeline_stage = None
        document.pipeline_stage_status = PipelineStageStatus.SUCCEEDED
        await session.commit()

        if pipeline_job_id:
            job_stmt = select(PipelineJob).where(PipelineJob.id == pipeline_job_id)
            job_result = await session.execute(job_stmt)
            job = job_result.scalar_one_or_none()
            if job:
                job.status = JobStatus.SUCCEEDED
                job.current_stage = "completed"
                job.progress_pct = 100
                await session.commit()

    return results


async def get_pipeline_status(
    session: AsyncSession,
    document_id: uuid.UUID,
) -> dict[str, Any]:
    """Get current pipeline status for a document."""
    # Get document
    doc_stmt = select(Document).where(Document.id == document_id)
    doc_result = await session.execute(doc_stmt)
    document = doc_result.scalar_one_or_none()
    if not document:
        raise ValueError(f"Document {document_id} not found")

    # Get latest version
    version = await get_latest_version(session, document_id)
    if not version:
        return {
            "document_id": str(document_id),
            "status": document.status.value,
            "current_stage": document.pipeline_stage.value if document.pipeline_stage else None,
            "pipeline_stage_status": document.pipeline_stage_status.value,
            "stages": {},
        }

    version_id = version.id

    # Check each stage completion status
    stages_status: dict[str, dict[str, Any]] = {}
    for stage in DEFAULT_PIPELINE_ORDER:
        handler = STAGE_HANDLERS.get(stage)
        if handler:
            is_complete = await handler.is_complete(session, document_id, version_id)
            stages_status[stage.value] = {
                "status": PipelineStageStatus.SUCCEEDED.value if is_complete else PipelineStageStatus.QUEUED.value,
                "complete": is_complete,
            }
        else:
            stages_status[stage.value] = {
                "status": PipelineStageStatus.SKIPPED.value,
                "complete": True,
            }

    # Determine current stage
    current_stage = None
    for stage in DEFAULT_PIPELINE_ORDER:
        if not stages_status[stage.value]["complete"]:
            current_stage = stage.value
            break

    if current_stage is None and document.status == DocumentStatus.READY:
        current_stage = "completed"

    # Determine the final current_stage value
    if current_stage:
        final_current_stage = current_stage
    elif document.pipeline_stage:
        final_current_stage = document.pipeline_stage.value
    else:
        final_current_stage = None

    return {
        "document_id": str(document_id),
        "status": document.status.value,
        "current_stage": final_current_stage,
        "pipeline_stage_status": document.pipeline_stage_status.value,
        "stages": stages_status,
    }