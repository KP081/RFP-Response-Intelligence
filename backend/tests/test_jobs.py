"""Integration tests for jobs module - async task queue."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import JobStatus, Org, OrgMembership, PipelineJob, Role, User
from app.modules.jobs.router import create_ping_job, get_job_status
from app.modules.jobs.schemas import JobCreate


class TestJobsRouter:
    """Tests for jobs router endpoints."""

    @pytest.fixture
    def current_user(self):
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def org(self, org_id):
        return Org(id=org_id, name="Test Org", settings={}, created_at=datetime.now(timezone.utc))

    @pytest.fixture
    def membership(self, org_id, current_user):
        return OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.ADMIN,
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def mock_request(self):
        request = MagicMock()
        request.headers = {}
        return request

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_session):
        with patch("app.modules.jobs.router.async_session_factory", return_value=mock_session):
            yield mock_session

    @pytest.mark.asyncio
    async def test_create_ping_job_enqueues_task(self, current_user, org_id, membership, mock_request, mock_session_factory, mock_session):
        """Test that create_ping_job enqueues a Celery task and returns job info."""
        correlation_id = "test-correlation-id"
        mock_request.headers = {"X-Correlation-ID": correlation_id}

        # Mock the pipeline job that would be created by the task
        job = PipelineJob(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=None,
            job_type="ping",
            status=JobStatus.QUEUED,
            current_stage=None,
            progress_pct=0,
            error_message=None,
            correlation_id=correlation_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_session.execute.return_value = mock_result

        with patch("app.modules.jobs.router.ping_task.apply_async") as mock_apply_async:
            mock_task = MagicMock()
            mock_task.id = "celery-task-id"
            mock_apply_async.return_value = mock_task

            result = await create_ping_job(
                org_id=org_id,
                membership=membership,
                current_user=current_user.id,
                request=mock_request,
                job_data=None,
            )

            assert result.id == job.id
            assert result.org_id == org_id
            assert result.job_type == "ping"
            assert result.status == "queued"
            assert result.correlation_id == correlation_id

            mock_apply_async.assert_called_once()
            call_kwargs = mock_apply_async.call_args.kwargs
            assert call_kwargs["kwargs"]["org_id"] == org_id
            assert call_kwargs["kwargs"]["correlation_id"] == correlation_id
            assert call_kwargs["kwargs"]["document_id"] is None

    @pytest.mark.asyncio
    async def test_create_ping_job_with_document_id(self, current_user, org_id, membership, mock_request, mock_session_factory, mock_session):
        """Test that create_ping_job accepts optional document_id."""
        correlation_id = "test-correlation-id"
        document_id = uuid.uuid4()
        mock_request.headers = {"X-Correlation-ID": correlation_id}

        job = PipelineJob(
            id=uuid.uuid4(),
            org_id=org_id,
            document_id=document_id,
            job_type="ping",
            status=JobStatus.QUEUED,
            current_stage=None,
            progress_pct=0,
            error_message=None,
            correlation_id=correlation_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_session.execute.return_value = mock_result

        with patch("app.modules.jobs.router.ping_task.apply_async") as mock_apply_async:
            mock_task = MagicMock()
            mock_task.id = "celery-task-id"
            mock_apply_async.return_value = mock_task

            job_data = JobCreate(job_type="ping", document_id=document_id)
            result = await create_ping_job(
                org_id=org_id,
                membership=membership,
                current_user=current_user.id,
                request=mock_request,
                job_data=job_data,
            )

            assert result.document_id == document_id
            call_kwargs = mock_apply_async.call_args.kwargs
            assert call_kwargs["kwargs"]["document_id"] == document_id

    @pytest.mark.asyncio
    async def test_get_job_status_returns_job(self, current_user, org_id, membership, mock_session):
        """Test that get_job_status returns the job with correct status."""
        job_id = uuid.uuid4()
        job = PipelineJob(
            id=job_id,
            org_id=org_id,
            document_id=None,
            job_type="ping",
            status=JobStatus.RUNNING,
            current_stage="ping_task",
            progress_pct=50,
            error_message=None,
            correlation_id="test-correlation-id",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_session.execute.return_value = mock_result

        result = await get_job_status(
            org_id=org_id,
            job_id=job_id,
            membership=membership,
            db_session=mock_session,
        )

        assert result.id == job_id
        assert result.org_id == org_id
        assert result.job_type == "ping"
        assert result.status == "running"
        assert result.current_stage == "ping_task"
        assert result.progress_pct == 50

    @pytest.mark.asyncio
    async def test_get_job_status_not_found_raises_404(self, current_user, org_id, membership, mock_session):
        """Test that get_job_status raises 404 for non-existent job."""
        job_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_job_status(
                org_id=org_id,
                job_id=job_id,
                membership=membership,
                db_session=mock_session,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Job not found"


class TestPipelineTaskDecorator:
    """Tests for the pipeline_task decorator."""

    @pytest.fixture
    def current_user(self):
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        
        # Mock refresh to set an ID on the job object
        async def mock_refresh(job_obj):
            if job_obj.id is None:
                job_obj.id = uuid.uuid4()
        session.refresh = AsyncMock(side_effect=mock_refresh)
        session.close = AsyncMock()
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_session):
        with patch("app.workers.tasks.async_session_factory", return_value=mock_session):
            yield mock_session

    @pytest.mark.asyncio
    async def test_pipeline_task_creates_job_record(self, current_user, org_id, mock_session_factory, mock_session):
        """Test that pipeline_task creates and updates job record through lifecycle."""
        from app.workers.tasks import _create_pipeline_job, _update_job_status

        correlation_id = "test-correlation-id"
        job_type = "test_job"

        # Create job
        job = await _create_pipeline_job(mock_session_factory, org_id, job_type, correlation_id)
        assert job.id is not None
        assert job.org_id == org_id
        assert job.job_type == job_type
        assert job.status == JobStatus.QUEUED
        assert job.correlation_id == correlation_id

        # Verify session.add and commit were called
        mock_session_factory.add.assert_called_once()
        mock_session_factory.commit.assert_called_once()
        mock_session_factory.refresh.assert_called_once()

        # Update to running
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_session_factory.execute.return_value = mock_result

        await _update_job_status(
            mock_session_factory, job.id, JobStatus.RUNNING, current_stage="test_stage", progress_pct=10
        )

        # Verify update
        assert mock_session_factory.commit.called

        # Update to succeeded
        await _update_job_status(
            mock_session_factory, job.id, JobStatus.SUCCEEDED, current_stage="completed", progress_pct=100
        )

        # Verify final state
        assert mock_session_factory.commit.called

    @pytest.mark.asyncio
    async def test_pipeline_task_handles_failure(self, current_user, org_id, mock_session_factory, mock_session):
        """Test that pipeline_task handles failure and records error message."""
        from app.workers.tasks import _create_pipeline_job, _update_job_status

        correlation_id = "test-correlation-id"
        job_type = "test_job"

        job = await _create_pipeline_job(mock_session_factory, org_id, job_type, correlation_id)

        # Update to failed with error
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_session_factory.execute.return_value = mock_result

        error_msg = "Something went wrong"
        await _update_job_status(
            mock_session_factory, job.id, JobStatus.FAILED, error_message=error_msg
        )

        # Verify failure state
        assert mock_session_factory.commit.called
        assert job.status == JobStatus.FAILED
        assert job.error_message == error_msg

    @pytest.mark.asyncio
    async def test_pipeline_task_retrying_status(self, current_user, org_id, mock_session_factory, mock_session):
        """Test that pipeline_task can set retrying status."""
        from app.workers.tasks import _create_pipeline_job, _update_job_status

        correlation_id = "test-correlation-id"
        job_type = "test_job"

        job = await _create_pipeline_job(mock_session_factory, org_id, job_type, correlation_id)

        # Update to retrying
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_session_factory.execute.return_value = mock_result

        await _update_job_status(
            mock_session_factory, job.id, JobStatus.RETRYING, error_message="Transient error"
        )

        # Verify retrying state
        assert mock_session_factory.commit.called
        assert job.status == JobStatus.RETRYING
        assert job.error_message == "Transient error"