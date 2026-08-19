"""Integration tests for pipeline orchestrator."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Chunk,
    Document,
    DocumentStatus,
    DocumentType,
    DocumentVersion,
    PipelineStageStatus,
    RawExtraction,
)
from app.modules.ingestion.pipeline import (
    ChunkStageHandler,
    EmbedStageHandler,
    ExtractStageHandler,
    get_pipeline_status,
    run_pipeline,
)
from app.modules.ingestion.pipeline import (
    PipelineStage as PipelineStageEnum,
)
from app.modules.ingestion.pipeline import (
    PipelineStageStatus as PipelineStageStatusEnum,
)


class TestPipelineOrchestrator:
    """Tests for the pipeline orchestrator."""

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def document_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def version_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = MagicMock()
        session.close = AsyncMock()
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_session):
        with patch("app.db.session.async_session_factory", return_value=mock_session):
            yield mock_session

    @pytest.mark.asyncio
    async def test_run_pipeline_success(self, org_id, document_id, version_id, mock_session_factory, mock_session):
        """Test successful pipeline execution."""
        # Setup document and version
        document = Document(
            id=document_id,
            org_id=org_id,
            uploaded_by_user_id=uuid.uuid4(),
            filename="test.pdf",
            mime_type="application/pdf",
            document_type=DocumentType.OTHER,
            status=DocumentStatus.UPLOADED,
            storage_key="test/key",
            size_bytes=1000,
        )

        version = DocumentVersion(
            id=version_id,
            org_id=org_id,
            document_id=document_id,
            storage_key="test/key",
            size_bytes=1000,
        )

        # Mock document query
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = document

        # Mock version query
        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version

        # Track extraction state
        created_extraction = RawExtraction(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document_id,
            version_id=version_id,
            blocks=[{"type": "text", "page": 1, "content": "Test content", "bbox": [0, 0, 100, 100]}],
            extractor_used="pdfplumber",
        )

        # Mock Chunk query for embed (not exists initially)
        embed_chunk_result = MagicMock()
        embed_chunk_result.scalar_one_or_none.return_value = None

        # Mock Chunk query (not exists initially)
        chunk_result = MagicMock()
        chunk_result.scalar_one_or_none.return_value = None

        # Use a flexible mock that returns appropriate values
        extract_stage_run = False
        
        def execute_side_effect(*args, **kwargs):
            nonlocal extract_stage_run
            # Get document query - return doc_result for any document query
            query_str = str(args[0]) if args else ""
            if "documents" in query_str and "WHERE documents.id" in query_str:
                return doc_result
            # Get version query
            elif "document_versions" in query_str:
                return version_result
            # RawExtraction is_complete checks
            elif "raw_extractions" in query_str:
                if extract_stage_run:
                    result = MagicMock()
                    result.scalar_one_or_none.return_value = created_extraction
                    return result
                else:
                    result = MagicMock()
                    result.scalar_one_or_none.return_value = None
                    return result
            # Chunk is_complete checks
            elif "chunks" in query_str and "embedding" not in query_str:
                return chunk_result
            # Embed is_complete check (chunks with embedding.is_not(None))
            elif "chunks" in query_str and "embedding" in query_str:
                return embed_chunk_result
            else:
                # For any subsequent calls (persistence), return a generic mock
                result = MagicMock()
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                return result

        mock_session.execute.side_effect = execute_side_effect
        
        def mock_extract(*args, **kwargs):
            nonlocal extract_stage_run
            extract_stage_run = True
            return [{"type": "text", "page": 1, "content": "Test content", "bbox": [0, 0, 100, 100]}]

        # Mock model_gateway.embed
        with patch("app.llm.gateway.get_model_gateway") as mock_get_gateway:
            mock_gateway = AsyncMock()
            mock_get_gateway.return_value = mock_gateway
            mock_gateway.embed.return_value = [[0.1] * 1536]

            # Mock extractors
            with patch("app.modules.ingestion.extraction.extract_pdf_content", side_effect=mock_extract):

                # Mock object store
                with patch("app.core.storage.get_object_store") as mock_store:
                    mock_store.return_value.get = AsyncMock(return_value=b"PDF content")

                    # Mock chunking
                    with patch("app.modules.ingestion.chunking.create_chunks_from_blocks") as mock_chunk:
                        mock_chunk.return_value = [{
                            "chunk_index": 0,
                            "content": "Test content",
                            "chunk_type": "text",
                            "page_start": 1,
                            "page_end": 1,
                            "section_path": None,
                            "token_count": 100,
                        }]

                        # Run pipeline
                        results = await run_pipeline(
                            session=mock_session,
                            org_id=org_id,
                            document_id=document_id,
                            correlation_id="test-correlation",
                        )

                        # Verify results
                        assert len(results) == 6  # All 6 stages (last 3 skipped)
                        assert all(r.status in (PipelineStageStatusEnum.SUCCEEDED, PipelineStageStatusEnum.SKIPPED) for r in results)
                        assert document.status == DocumentStatus.READY

    @pytest.mark.asyncio
    async def test_run_pipeline_idempotency_extract_complete(self, org_id, document_id, version_id, mock_session_factory, mock_session):
        """Test that extract stage is skipped if already complete."""
        # Setup document
        document = Document(
            id=document_id,
            org_id=org_id,
            uploaded_by_user_id=uuid.uuid4(),
            filename="test.pdf",
            mime_type="application/pdf",
            document_type=DocumentType.OTHER,
            status=DocumentStatus.UPLOADED,
            storage_key="test/key",
            size_bytes=1000,
        )

        version = DocumentVersion(
            id=version_id,
            org_id=org_id,
            document_id=document_id,
            storage_key="test/key",
            size_bytes=1000,
        )

        # Mock RawExtraction EXISTS (already extracted)
        existing_extraction = RawExtraction(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document_id,
            version_id=version_id,
            blocks=[{"type": "text", "page": 1, "content": "Test", "bbox": [0, 0, 100, 100]}],
            extractor_used="pdfplumber",
        )

        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = document

        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version

        extraction_result = MagicMock()
        extraction_result.scalar_one_or_none.return_value = existing_extraction

        chunk_result = MagicMock()
        chunk_result.scalar_one_or_none.return_value = None

        embed_chunk_result = MagicMock()
        embed_chunk_result.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [
            doc_result,  # get document
            version_result,  # get version
            extraction_result,  # extract is_complete - EXISTS
            chunk_result,  # chunk is_complete - NOT EXISTS
            chunk_result,  # embed is_complete - NOT EXISTS
        ]

        with patch("app.llm.gateway.get_model_gateway") as mock_get_gateway:
            mock_gateway = AsyncMock()
            mock_get_gateway.return_value = mock_gateway
            mock_gateway.embed.return_value = [[0.1] * 1536]

            with patch("app.modules.ingestion.chunking.create_chunks_from_blocks") as mock_chunk:
                mock_chunk.return_value = [{
                    "chunk_index": 0,
                    "content": "Test content",
                    "chunk_type": "text",
                    "page_start": 1,
                    "page_end": 1,
                    "section_path": None,
                    "token_count": 100,
                }]

                results = await run_pipeline(
                    session=mock_session,
                    org_id=org_id,
                    document_id=document_id,
                    correlation_id="test-correlation",
                )

                # Extract should be skipped
                extract_result = next(r for r in results if r.stage == PipelineStageEnum.EXTRACT)
                assert extract_result.status == PipelineStageStatusEnum.SKIPPED

    @pytest.mark.asyncio
    async def test_run_pipeline_failure_embedding(self, org_id, document_id, version_id, mock_session_factory, mock_session):
        """Test pipeline failure at embedding stage."""
        document = Document(
            id=document_id,
            org_id=org_id,
            uploaded_by_user_id=uuid.uuid4(),
            filename="test.pdf",
            mime_type="application/pdf",
            document_type=DocumentType.OTHER,
            status=DocumentStatus.UPLOADED,
            storage_key="test/key",
            size_bytes=1000,
        )

        version = DocumentVersion(
            id=version_id,
            org_id=org_id,
            document_id=document_id,
            storage_key="test/key",
            size_bytes=1000,
        )

        # Mock RawExtraction EXISTS
        existing_extraction = RawExtraction(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document_id,
            version_id=version_id,
            blocks=[{"type": "text", "page": 1, "content": "Test", "bbox": [0, 0, 100, 100]}],
            extractor_used="pdfplumber",
        )

        # Mock Chunk EXISTS
        existing_chunk = Chunk(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document_id,
            version_id=version_id,
            chunk_index=0,
            content="Test content",
            chunk_type="text",
            page_start=1,
            page_end=1,
            token_count=100,
        )

        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = document

        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version

        extraction_result = MagicMock()
        extraction_result.scalar_one_or_none.return_value = existing_extraction

        chunk_result = MagicMock()
        chunk_result.scalar_one_or_none.return_value = existing_chunk

        # For embed is_complete: existing_chunk has embedding=None, so is_not(None) returns empty
        embed_chunk_result = MagicMock()
        embed_chunk_result.scalar_one_or_none.return_value = None

        # For embed_document_chunks query: chunks without embeddings (existing_chunk has embedding=None)
        # This query selects Chunk.id, so we need to return the chunk ID
        chunks_without_embeddings_result = MagicMock()
        chunks_without_embeddings_scalars = MagicMock()
        chunks_without_embeddings_scalars.all.return_value = [existing_chunk.id]
        chunks_without_embeddings_result.scalars.return_value = chunks_without_embeddings_scalars

        # For embed_chunks query: Chunk.id.in_(chunk_ids)
        # This returns the full Chunk object
        chunks_for_embedding_result = MagicMock()
        chunks_for_embedding_scalars = MagicMock()
        chunks_for_embedding_scalars.all.return_value = [existing_chunk]
        chunks_for_embedding_result.scalars.return_value = chunks_for_embedding_scalars

        # Use flexible mock for execute
        def execute_side_effect(*args, **kwargs):
            query_str = str(args[0]) if args else ""
            if "documents" in query_str and "WHERE documents.id" in query_str:
                return doc_result
            elif "document_versions" in query_str:
                return version_result
            elif "raw_extractions" in query_str:
                return extraction_result
            elif "chunks" in query_str and "embedding IS NOT NULL" in query_str:
                # embed is_complete check - no chunks with embeddings
                return embed_chunk_result
            elif "chunks" in query_str and "embedding IS NULL" in query_str:
                # embed_document_chunks query - chunks without embeddings (selects Chunk.id)
                return chunks_without_embeddings_result
            elif "chunks" in query_str and "chunks.id IN" in query_str:
                # embed_chunks query - chunks by ID
                return chunks_for_embedding_result
            elif "chunks" in query_str:
                return chunk_result
            else:
                result = MagicMock()
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                return result

        mock_session.execute.side_effect = execute_side_effect

        with patch("app.llm.gateway.get_model_gateway") as mock_get_gateway:
            mock_gateway = AsyncMock()
            mock_get_gateway.return_value = mock_gateway
            mock_gateway.embed.side_effect = Exception("Embedding API failed")

            results = await run_pipeline(
                session=mock_session,
                org_id=org_id,
                document_id=document_id,
                correlation_id="test-correlation",
            )

            # Embed should fail
            embed_result = next(r for r in results if r.stage == PipelineStageEnum.EMBED)
            assert embed_result.status == PipelineStageStatusEnum.FAILED
            assert embed_result.error == "Embedding API failed"

            # Document should be marked failed
            assert document.status == DocumentStatus.FAILED
            assert document.pipeline_stage == PipelineStageEnum.EMBED
            assert document.pipeline_stage_status == PipelineStageStatusEnum.FAILED

    @pytest.mark.asyncio
    async def test_run_pipeline_resume_from_embedding(self, org_id, document_id, version_id, mock_session_factory, mock_session):
        """Test pipeline resume from failed embedding stage."""
        document = Document(
            id=document_id,
            org_id=org_id,
            uploaded_by_user_id=uuid.uuid4(),
            filename="test.pdf",
            mime_type="application/pdf",
            document_type=DocumentType.OTHER,
            status=DocumentStatus.FAILED,
            storage_key="test/key",
            size_bytes=1000,
            pipeline_stage=PipelineStageEnum.EMBED,
            pipeline_stage_status=PipelineStageStatusEnum.FAILED,
        )

        version = DocumentVersion(
            id=version_id,
            org_id=org_id,
            document_id=document_id,
            storage_key="test/key",
            size_bytes=1000,
        )

        # Mock RawExtraction EXISTS
        existing_extraction = RawExtraction(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document_id,
            version_id=version_id,
            blocks=[{"type": "text", "page": 1, "content": "Test", "bbox": [0, 0, 100, 100]}],
            extractor_used="pdfplumber",
        )

        # Mock Chunk EXISTS
        existing_chunk = Chunk(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document_id,
            version_id=version_id,
            chunk_index=0,
            content="Test content",
            chunk_type="text",
            page_start=1,
            page_end=1,
            token_count=100,
        )

        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = document

        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version

        extraction_result = MagicMock()
        extraction_result.scalar_one_or_none.return_value = existing_extraction

        chunk_result = MagicMock()
        chunk_result.scalar_one_or_none.return_value = existing_chunk

        embed_chunk_result = MagicMock()
        # embed is_complete check - existing_chunk has embedding=None, so is_not(None) returns empty
        embed_chunk_result.scalars.return_value.all.return_value = []

        # Use flexible mock for execute
        call_count = 0
        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return doc_result  # get document
            elif call_count == 2:
                return version_result  # get version
            elif call_count == 3:
                return embed_chunk_result  # embed is_complete
            else:
                # For subsequent calls (OCR, caption, dedupe is_complete)
                result = MagicMock()
                result.scalar_one_or_none.return_value = True  # always True for conditional stages
                result.scalars.return_value.all.return_value = []
                return result

        mock_session.execute.side_effect = execute_side_effect

        with patch("app.llm.gateway.get_model_gateway") as mock_get_gateway:
            mock_gateway = AsyncMock()
            mock_get_gateway.return_value = mock_gateway
            mock_gateway.embed.return_value = [[0.1] * 1536]

            results = await run_pipeline(
                session=mock_session,
                org_id=org_id,
                document_id=document_id,
                correlation_id="test-correlation",
                start_from_stage=PipelineStageEnum.EMBED,
            )

            # Only embed and subsequent stages should run
            assert len(results) == 4  # embed, ocr, caption_figures, dedupe
            embed_result = next(r for r in results if r.stage == PipelineStageEnum.EMBED)
            assert embed_result.status == PipelineStageStatusEnum.SUCCEEDED

            # Extract and chunk should not be in results
            stages_run = [r.stage for r in results]
            assert PipelineStageEnum.EXTRACT not in stages_run
            assert PipelineStageEnum.CHUNK not in stages_run


class TestPipelineStatus:
    """Tests for pipeline status endpoint."""

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def document_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def version_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_get_pipeline_status_ready(self, org_id, document_id, version_id, mock_session):
        """Test get_pipeline_status for a ready document."""
        document = Document(
            id=document_id,
            org_id=org_id,
            uploaded_by_user_id=uuid.uuid4(),
            filename="test.pdf",
            mime_type="application/pdf",
            document_type=DocumentType.OTHER,
            status=DocumentStatus.READY,
            storage_key="test/key",
            size_bytes=1000,
            pipeline_stage=None,
            pipeline_stage_status=PipelineStageStatus.SUCCEEDED,
        )

        version = DocumentVersion(
            id=version_id,
            org_id=org_id,
            document_id=document_id,
            storage_key="test/key",
            size_bytes=1000,
        )

        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = document

        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version

        # All stages complete
        extraction_result = MagicMock()
        extraction_result.scalar_one_or_none.return_value = RawExtraction(
            id=uuid.uuid4(), org_id=org_id, document_id=document_id, version_id=version_id,
            blocks=[], extractor_used="pdfplumber"
        )

        chunk_result = MagicMock()
        chunk_result.scalar_one_or_none.return_value = Chunk(
            id=uuid.uuid4(), org_id=org_id, document_id=document_id, version_id=version_id,
            chunk_index=0, content="test", chunk_type="text", page_start=1, page_end=1, token_count=100
        )

        embed_chunk_result = MagicMock()
        embed_chunk_result.scalars.return_value.all.return_value = [
            Chunk(
                id=uuid.uuid4(), org_id=org_id, document_id=document_id, version_id=version_id,
                chunk_index=0, content="test", chunk_type="text", page_start=1, page_end=1,
                token_count=100, embedding=[0.1]*1536
            )
        ]

        mock_session.execute.side_effect = [
            doc_result,  # get document
            version_result,  # get version
            extraction_result,  # extract is_complete
            chunk_result,  # chunk is_complete
            embed_chunk_result,  # embed is_complete
            MagicMock(scalar_one_or_none=MagicMock(return_value=True)),  # ocr is_complete (always True)
            MagicMock(scalar_one_or_none=MagicMock(return_value=True)),  # caption_figures is_complete (always True)
            MagicMock(scalar_one_or_none=MagicMock(return_value=True)),  # dedupe is_complete (always True)
        ]

        status = await get_pipeline_status(mock_session, document_id)

        assert status["status"] == "ready"
        assert status["current_stage"] == "completed"
        assert all(s["complete"] for s in status["stages"].values())


class TestPipelineStageHandlers:
    """Tests for individual stage handlers."""

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def document_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def version_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_extract_stage_handler_is_complete(self, org_id, document_id, version_id, mock_session):
        """Test ExtractStageHandler.is_complete."""
        handler = ExtractStageHandler()

        # Not complete - no extraction
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result

        is_complete = await handler.is_complete(mock_session, document_id, version_id)
        assert is_complete is False

        # Complete - extraction exists
        result.scalar_one_or_none.return_value = RawExtraction(
            id=uuid.uuid4(), org_id=org_id, document_id=document_id, version_id=version_id,
            blocks=[], extractor_used="pdfplumber"
        )

        is_complete = await handler.is_complete(mock_session, document_id, version_id)
        assert is_complete is True

    @pytest.mark.asyncio
    async def test_chunk_stage_handler_is_complete(self, org_id, document_id, version_id, mock_session):
        """Test ChunkStageHandler.is_complete."""
        handler = ChunkStageHandler()

        # Not complete - no chunks
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result

        is_complete = await handler.is_complete(mock_session, document_id, version_id)
        assert is_complete is False

        # Complete - chunks exist
        result.scalar_one_or_none.return_value = Chunk(
            id=uuid.uuid4(), org_id=org_id, document_id=document_id, version_id=version_id,
            chunk_index=0, content="test", chunk_type="text", page_start=1, page_end=1, token_count=100
        )

        is_complete = await handler.is_complete(mock_session, document_id, version_id)
        assert is_complete is True

    @pytest.mark.asyncio
    async def test_embed_stage_handler_is_complete(self, org_id, document_id, version_id, mock_session):
        """Test EmbedStageHandler.is_complete."""
        handler = EmbedStageHandler()

        # Not complete - chunks without embeddings
        result = MagicMock()
        # Mock scalar_one_or_none() to return None (simulating is_not(None) filter returning empty)
        result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result

        is_complete = await handler.is_complete(mock_session, document_id, version_id)
        assert is_complete is False

        # Complete - chunks with embeddings (is_not(None) filter returns chunks)
        result.scalar_one_or_none.return_value = Chunk(
            id=uuid.uuid4(), org_id=org_id, document_id=document_id, version_id=version_id,
            chunk_index=0, content="test", chunk_type="text", page_start=1, page_end=1,
            token_count=100, embedding=[0.1]*1536
        )

        is_complete = await handler.is_complete(mock_session, document_id, version_id)
        assert is_complete is True