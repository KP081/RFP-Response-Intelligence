"""Tests for ingestion router SSE JSON serialization."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    DocumentStatus,
    DocumentType,
    PipelineStageStatus,
    User,
)
from app.modules.documents.router import upload_document


class TestSSEJSONSerialization:
    """Tests for SSE event JSON serialization."""

    def test_json_dumps_with_default_str_handles_datetime(self):
        """Test that json.dumps with default=str handles datetime objects."""
        status = {
            "document_id": str(uuid.uuid4()),
            "status": "processing",
            "current_stage": "extract",
            "pipeline_stage_status": "running",
            "started_at": datetime(2024, 1, 15, 10, 30, 0),
            "stages": {
                "extract": {"status": "running", "complete": False},
            },
        }

        # This should not raise
        json_str = json.dumps(status, default=str)
        parsed = json.loads(json_str)

        assert parsed["started_at"] == "2024-01-15 10:30:00"

    def test_json_dumps_with_default_str_handles_uuid(self):
        """Test that json.dumps with default=str handles UUID objects."""
        doc_id = uuid.uuid4()
        status = {
            "document_id": doc_id,
            "status": "processing",
            "current_stage": "extract",
            "pipeline_stage_status": "running",
            "stages": {
                "extract": {"status": "running", "complete": False},
            },
        }

        # This should not raise
        json_str = json.dumps(status, default=str)
        parsed = json.loads(json_str)

        assert parsed["document_id"] == str(doc_id)

    def test_json_dumps_with_default_str_handles_none(self):
        """Test that json.dumps with default=str handles None values."""
        status = {
            "document_id": str(uuid.uuid4()),
            "status": "uploaded",
            "current_stage": None,
            "pipeline_stage_status": "queued",
            "stages": {
                "extract": {"status": "queued", "complete": False},
            },
        }

        # This should not raise
        json_str = json.dumps(status, default=str)
        parsed = json.loads(json_str)

        assert parsed["current_stage"] is None

    def test_json_dumps_without_default_str_raises_on_datetime(self):
        """Test that json.dumps without default=str raises on datetime."""
        status = {
            "started_at": datetime(2024, 1, 15, 10, 30, 0),
        }

        with pytest.raises(TypeError):
            json.dumps(status)  # No default=str

    def test_sse_event_format(self):
        """Test that SSE event format is correct."""
        status = {
            "document_id": str(uuid.uuid4()),
            "status": "processing",
            "current_stage": "extract",
            "pipeline_stage_status": "running",
            "stages": {
                "extract": {"status": "running", "complete": False},
            },
        }

        # Simulate the SSE event format
        event = f"data: {json.dumps(status, default=str)}\n\n"

        # Verify format
        assert event.startswith("data: ")
        assert event.endswith("\n\n")

        # Extract and parse JSON
        json_payload = event[len("data: "):-2]  # Remove "data: " prefix and "\n\n" suffix
        parsed = json.loads(json_payload)

        assert "document_id" in parsed
        assert "status" in parsed
        assert "current_stage" in parsed
        assert "pipeline_stage_status" in parsed
        assert "stages" in parsed

    def test_multiple_sse_events(self):
        """Test multiple SSE events can be parsed."""
        events = []
        for i in range(3):
            status = {
                "document_id": str(uuid.uuid4()),
                "status": "processing",
                "current_stage": "extract" if i == 0 else "chunk" if i == 1 else "embed",
                "pipeline_stage_status": "running",
                "stages": {
                    "extract": {"status": "running" if i == 0 else "succeeded", "complete": i > 0},
                    "chunk": {"status": "queued" if i < 2 else "running", "complete": i > 1},
                    "embed": {"status": "queued", "complete": False},
                },
            }
            event = f"data: {json.dumps(status, default=str)}\n\n"
            events.append(event)

        # Parse all events
        for event in events:
            json_payload = event[len("data: "):-2]
            parsed = json.loads(json_payload)
            assert "document_id" in parsed
            assert "status" in parsed
            assert "current_stage" in parsed


class TestCorrelationIdPropagation:
    """Tests for correlation ID propagation in document upload."""

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def current_user(self):
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def membership(self, org_id, current_user):
        from app.db.models import OrgMembership, Role
        return OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.ADMIN,
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        session.refresh = AsyncMock()
        return session

    @pytest.fixture
    def mock_documents_service(self):
        from app.modules.documents.service import DocumentsService
        service = AsyncMock(spec=DocumentsService)
        return service

    @pytest.fixture
    def mock_upload_file(self):
        file = AsyncMock()
        file.filename = "test.pdf"
        file.content_type = "application/pdf"
        file.read = AsyncMock(return_value=b"test content")
        return file

    @pytest.mark.asyncio
    async def test_upload_document_uses_request_correlation_id(
        self, org_id, current_user, membership, mock_session, mock_documents_service, mock_upload_file
    ):
        """Test that upload_document propagates the real correlation ID from request headers."""
        from app.db.models import Document

        # Mock document returned by service
        document = Document(
            id=uuid.uuid4(),
            org_id=org_id,
            uploaded_by_user_id=current_user.id,
            filename="test.pdf",
            mime_type="application/pdf",
            document_type=DocumentType.OTHER,
            status=DocumentStatus.UPLOADED,
            storage_key="test/key",
            size_bytes=1000,
            created_at=datetime.now(timezone.utc),
        )
        mock_documents_service.upload_document.return_value = document

        # Mock request with correlation ID
        request = MagicMock(spec=Request)
        request.headers = {"X-Correlation-ID": "test-correlation-123"}

        # Mock the Celery task
        with patch("app.modules.documents.router.get_run_ingestion_pipeline") as mock_get_pipeline:
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            await upload_document(
                org_id=org_id,
                file=mock_upload_file,
                request=request,
                document_type=DocumentType.OTHER,
                membership=membership,
                current_user=current_user,
                documents_service=mock_documents_service,
                session=mock_session,
            )

            # Verify the task was called with the correlation ID from request headers
            mock_get_pipeline.assert_called_once()
            mock_pipeline.delay.assert_called_once()
            call_kwargs = mock_pipeline.delay.call_args.kwargs
            assert call_kwargs["correlation_id"] == "test-correlation-123"
            assert call_kwargs["org_id"] == org_id
            assert call_kwargs["document_id"] == document.id

    @pytest.mark.asyncio
    async def test_upload_document_fallback_correlation_id(
        self, org_id, current_user, membership, mock_session, mock_documents_service, mock_upload_file
    ):
        """Test that upload_document falls back to synthetic ID when header is absent."""
        from app.db.models import Document

        document = Document(
            id=uuid.uuid4(),
            org_id=org_id,
            uploaded_by_user_id=current_user.id,
            filename="test.pdf",
            mime_type="application/pdf",
            document_type=DocumentType.OTHER,
            status=DocumentStatus.UPLOADED,
            storage_key="test/key",
            size_bytes=1000,
            created_at=datetime.now(timezone.utc),
        )
        mock_documents_service.upload_document.return_value = document

        # Request without X-Correlation-ID header
        request = MagicMock(spec=Request)
        request.headers = {}

        with patch("app.modules.documents.router.get_run_ingestion_pipeline") as mock_get_pipeline:
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            await upload_document(
                org_id=org_id,
                file=mock_upload_file,
                request=request,
                document_type=DocumentType.OTHER,
                membership=membership,
                current_user=current_user,
                documents_service=mock_documents_service,
                session=mock_session,
            )

            mock_get_pipeline.assert_called_once()
            mock_pipeline.delay.assert_called_once()
            call_kwargs = mock_pipeline.delay.call_args.kwargs
            assert call_kwargs["correlation_id"] == f"ingest-{document.id}"

    @pytest.mark.asyncio
    async def test_retry_document_pipeline_uses_request_correlation_id(
        self, org_id, current_user, membership, mock_session
    ):
        """Test that retry_document_pipeline uses correlation ID from request headers."""
        from app.modules.ingestion.router import retry_document_pipeline

        document = Document(
            id=uuid.uuid4(),
            org_id=org_id,
            uploaded_by_user_id=current_user.id,
            filename="test.pdf",
            mime_type="application/pdf",
            document_type=DocumentType.OTHER,
            status=DocumentStatus.FAILED,
            storage_key="test/key",
            size_bytes=1000,
            created_at=datetime.now(timezone.utc),
            pipeline_stage_status=PipelineStageStatus.FAILED,
            pipeline_stage="embed",
        )

        # Mock get_document_dep to return our document
        with patch("app.modules.ingestion.router.get_document_dep", return_value=document):
            request = MagicMock(spec=Request)
            request.headers = {"X-Correlation-ID": "retry-correlation-456"}

            with patch("app.modules.ingestion.router.get_retry_ingestion_pipeline") as mock_get_retry:
                mock_retry_task = MagicMock()
                mock_get_retry.return_value = mock_retry_task

                result = await retry_document_pipeline(
                    org_id=org_id,
                    document=document,
                    membership=membership,
                    current_user=current_user,
                    request=request,
                    db_session=mock_session,
                )

                assert result["correlation_id"] == "retry-correlation-456"
                mock_retry_task.delay.assert_called_once_with(
                    org_id=org_id,
                    correlation_id="retry-correlation-456",
                    document_id=document.id,
                )