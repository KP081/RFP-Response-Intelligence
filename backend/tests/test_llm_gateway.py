"""Tests for the LLM Model Gateway."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMCall, LLMCallStatus
from app.llm.gateway import ModelGateway, build_messages
from app.llm.providers.base import LLMResponse, TokenUsage
from app.llm.schemas import SmokeTestResult


class TestBuildMessages:
    """Tests for the build_messages prompt-injection safety helper."""

    def test_build_messages_basic(self):
        """Test basic message building with document content isolation."""
        messages = build_messages(
            system_instructions="You are an analyzer.",
            untrusted_document_content="<doc>Secret RFP content</doc>",
            user_task="Extract requirements.",
        )

        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are an analyzer."
        assert messages[1]["role"] == "user"
        assert "<document_content>\n<doc>Secret RFP content</doc>\n</document_content>" in messages[1]["content"]
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Extract requirements."

    def test_build_messages_special_characters(self):
        """Test that special characters in document content are handled."""
        messages = build_messages(
            system_instructions="System prompt",
            untrusted_document_content="Content with \"quotes\" and <tags> and {braces}",
            user_task="Analyze",
        )

        assert "<document_content>\nContent with \"quotes\" and <tags> and {braces}\n</document_content>" in messages[1]["content"]


class TestModelGateway:
    """Tests for the ModelGateway class."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        from unittest.mock import AsyncMock, MagicMock
        
        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.set = AsyncMock(return_value=True)
        return redis_mock

    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        session = AsyncMock(spec=AsyncSession)
        session.add = MagicMock()
        session.commit = AsyncMock()
        
        # The session factory returns an async context manager
        async_session_cm = AsyncMock()
        async_session_cm.__aenter__ = AsyncMock(return_value=session)
        async_session_cm.__aexit__ = AsyncMock(return_value=None)
        
        session_factory = MagicMock(return_value=async_session_cm)
        return session_factory

    @pytest.fixture
    def gateway(self, mock_redis, mock_session_factory):
        """Create a ModelGateway with mocked dependencies."""
        with patch("app.llm.gateway.get_provider") as mock_get_provider:
            mock_provider = AsyncMock()
            mock_get_provider.return_value = mock_provider
            gateway = ModelGateway(
                redis_client=mock_redis,
                session_factory=mock_session_factory,
            )
            gateway.provider = mock_provider
            return gateway

    @pytest.fixture
    def org_id(self):
        """Generate a test org_id."""
        return uuid.uuid4()

    @pytest.fixture
    def correlation_id(self):
        """Generate a test correlation_id."""
        return str(uuid.uuid4())

    async def test_complete_success_logs_call(
        self,
        gateway: ModelGateway,
        org_id: uuid.UUID,
        correlation_id: str,
        mock_session_factory,
    ):
        """Test that successful complete() logs an llm_calls row."""
        # Arrange
        mock_response = LLMResponse(
            content='{"status": "ok"}',
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            model="gpt-4o-mini",
            raw_response={},
        )
        gateway.provider.complete = AsyncMock(return_value=mock_response)
        gateway.provider.estimate_cost = MagicMock(return_value=0.001)

        # Act
        result = await gateway.complete(
            org_id=org_id,
            task_type="smoke_test",
            prompt="Test prompt",
            model_tier="fast",
            response_schema=SmokeTestResult,
            correlation_id=correlation_id,
        )

        # Assert
        assert isinstance(result, SmokeTestResult)
        assert result.status == "ok"

        # Verify session was used to log
        session = mock_session_factory.return_value.__aenter__.return_value
        session.add.assert_called_once()
        session.commit.assert_called_once()

        # Verify the logged call
        logged_call = session.add.call_args[0][0]
        assert isinstance(logged_call, LLMCall)
        assert logged_call.org_id == org_id
        assert logged_call.task_type == "smoke_test"
        assert logged_call.model_tier == "fast"
        assert logged_call.model_name == "gpt-4o-mini"
        assert logged_call.correlation_id == correlation_id
        assert logged_call.input_tokens == 100
        assert logged_call.output_tokens == 50
        assert logged_call.status == LLMCallStatus.SUCCESS
        assert logged_call.cost_estimate == 0.001

    async def test_complete_cache_hit_logs_call(
        self,
        gateway: ModelGateway,
        org_id: uuid.UUID,
        correlation_id: str,
        mock_redis,
        mock_session_factory,
    ):
        """Test that cache hit returns cached result and logs cache_hit."""
        # Arrange
        mock_redis.get = AsyncMock(return_value='{"content": {"status": "ok"}}')

        # Act
        result = await gateway.complete(
            org_id=org_id,
            task_type="smoke_test",
            prompt="Test prompt",
            model_tier="fast",
            response_schema=SmokeTestResult,
            cache_key="test-cache-key",
            correlation_id=correlation_id,
        )

        # Assert
        assert isinstance(result, SmokeTestResult)
        assert result.status == "ok"

        # Verify provider was NOT called
        gateway.provider.complete.assert_not_called()

        # Verify cache hit was logged
        session = mock_session_factory.return_value.__aenter__.return_value
        session.add.assert_called_once()
        logged_call = session.add.call_args[0][0]
        assert logged_call.status == LLMCallStatus.CACHE_HIT
        assert logged_call.input_tokens == 0
        assert logged_call.output_tokens == 0
        assert logged_call.cost_estimate == 0.0

    async def test_complete_second_call_with_same_cache_key_returns_cached(
        self,
        gateway: ModelGateway,
        org_id: uuid.UUID,
        correlation_id: str,
        mock_redis,
        mock_session_factory,
    ):
        """Test that second call with same cache_key returns cached result without provider call."""
        # Arrange
        mock_response = LLMResponse(
            content='{"status": "ok"}',
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            model="gpt-4o-mini",
            raw_response={},
        )
        gateway.provider.complete = AsyncMock(return_value=mock_response)
        gateway.provider.estimate_cost = MagicMock(return_value=0.001)

        # First call - cache miss, provider called
        mock_redis.get = AsyncMock(return_value=None)
        await gateway.complete(
            org_id=org_id,
            task_type="smoke_test",
            prompt="Test prompt",
            model_tier="fast",
            response_schema=SmokeTestResult,
            cache_key="test-cache-key",
            correlation_id=correlation_id,
        )

        # Verify provider was called once
        assert gateway.provider.complete.call_count == 1

        # Second call - cache hit
        mock_redis.get = AsyncMock(return_value='{"content": {"status": "ok"}}')
        gateway.provider.complete = AsyncMock(return_value=mock_response)  # reset

        result = await gateway.complete(
            org_id=org_id,
            task_type="smoke_test",
            prompt="Test prompt",
            model_tier="fast",
            response_schema=SmokeTestResult,
            cache_key="test-cache-key",
            correlation_id=correlation_id,
        )

        # Assert provider was NOT called again
        gateway.provider.complete.assert_not_called()
        assert isinstance(result, SmokeTestResult)

    async def test_complete_structured_output_validation_retry(
        self,
        gateway: ModelGateway,
        org_id: uuid.UUID,
        correlation_id: str,
        mock_session_factory,
    ):
        """Test that invalid structured output triggers one retry then succeeds."""
        # Arrange: first response invalid, second valid
        invalid_response = LLMResponse(
            content="not valid json",
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            model="gpt-4o-mini",
            raw_response={},
        )
        valid_response = LLMResponse(
            content='{"status": "ok"}',
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            model="gpt-4o-mini",
            raw_response={},
        )
        gateway.provider.complete = AsyncMock(side_effect=[invalid_response, valid_response])
        gateway.provider.estimate_cost = MagicMock(return_value=0.001)

        # Act
        result = await gateway.complete(
            org_id=org_id,
            task_type="smoke_test",
            prompt="Test prompt",
            model_tier="fast",
            response_schema=SmokeTestResult,
            correlation_id=correlation_id,
        )

        # Assert
        assert isinstance(result, SmokeTestResult)
        assert result.status == "ok"
        assert gateway.provider.complete.call_count == 2

        # Verify only one success call was logged (not two)
        session = mock_session_factory.return_value.__aenter__.return_value
        assert session.add.call_count == 1
        logged_call = session.add.call_args[0][0]
        assert logged_call.status == LLMCallStatus.SUCCESS

    async def test_complete_structured_output_validation_fails_after_retry(
        self,
        gateway: ModelGateway,
        org_id: uuid.UUID,
        correlation_id: str,
        mock_session_factory,
    ):
        """Test that invalid structured output after retry logs failure."""
        # Arrange: both responses invalid
        invalid_response = LLMResponse(
            content="not valid json",
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            model="gpt-4o-mini",
            raw_response={},
        )
        gateway.provider.complete = AsyncMock(return_value=invalid_response)
        gateway.provider.estimate_cost = MagicMock(return_value=0.001)

        # Act & Assert
        with pytest.raises(Exception):
            await gateway.complete(
                org_id=org_id,
                task_type="smoke_test",
                prompt="Test prompt",
                model_tier="fast",
                response_schema=SmokeTestResult,
                correlation_id=correlation_id,
            )

        # Verify provider was called twice (initial + retry)
        assert gateway.provider.complete.call_count == 2

        # Verify failure was logged
        session = mock_session_factory.return_value.__aenter__.return_value
        assert session.add.call_count == 1
        logged_call = session.add.call_args[0][0]
        assert logged_call.status == LLMCallStatus.FAILED

    async def test_complete_without_schema_returns_string(
        self,
        gateway: ModelGateway,
        org_id: uuid.UUID,
        correlation_id: str,
        mock_session_factory,
    ):
        """Test that complete() without response_schema returns raw string."""
        # Arrange
        mock_response = LLMResponse(
            content="Raw text response",
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            model="gpt-4o-mini",
            raw_response={},
        )
        gateway.provider.complete = AsyncMock(return_value=mock_response)
        gateway.provider.estimate_cost = MagicMock(return_value=0.001)

        # Act
        result = await gateway.complete(
            org_id=org_id,
            task_type="smoke_test",
            prompt="Test prompt",
            model_tier="fast",
            correlation_id=correlation_id,
        )

        # Assert
        assert result == "Raw text response"
        assert isinstance(result, str)

    async def test_embed_success_logs_call(
        self,
        gateway: ModelGateway,
        org_id: uuid.UUID,
        correlation_id: str,
        mock_session_factory,
    ):
        """Test that embed() logs an llm_calls row."""
        # Arrange
        gateway.provider.embed = AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])
        gateway.provider.estimate_cost = MagicMock(return_value=0.0001)

        # Act
        result = await gateway.embed(
            org_id=org_id,
            task_type="embedding_generation",
            texts=["text1", "text2"],
            model_tier="fast",
            correlation_id=correlation_id,
        )

        # Assert
        assert len(result) == 2
        assert len(result[0]) == 1536

        # Verify logged
        session = mock_session_factory.return_value.__aenter__.return_value
        session.add.assert_called_once()
        logged_call = session.add.call_args[0][0]
        assert logged_call.task_type == "embedding_generation"
        assert logged_call.status == LLMCallStatus.SUCCESS
        assert logged_call.input_tokens > 0

    async def test_embed_cache_hit(
        self,
        gateway: ModelGateway,
        org_id: uuid.UUID,
        correlation_id: str,
        mock_redis,
        mock_session_factory,
    ):
        """Test that embed() cache hit returns cached embeddings."""
        # Arrange
        import json
        cached_embeddings = [[0.1] * 1536, [0.2] * 1536]
        mock_redis.get.return_value = json.dumps({"content": cached_embeddings})

        # Act
        result = await gateway.embed(
            org_id=org_id,
            task_type="embedding_generation",
            texts=["text1", "text2"],
            model_tier="fast",
            cache_key="embed-cache-key",
            correlation_id=correlation_id,
        )

        # Assert
        assert result == cached_embeddings
        gateway.provider.embed.assert_not_called()

        # Verify cache hit logged
        session = mock_session_factory.return_value.__aenter__.return_value
        logged_call = session.add.call_args[0][0]
        assert logged_call.status == LLMCallStatus.CACHE_HIT


class TestPromptTemplates:
    """Tests for prompt template rendering."""

    def test_render_prompt_uses_build_messages(self):
        """Test that render_prompt uses build_messages for safety."""
        from app.llm.prompts import render_prompt

        messages = render_prompt(
            name="smoke_test",
            version="v1",
            document_content="<doc>Test content</doc>",
        )

        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert "<document_content>\n<doc>Test content</doc>\n</document_content>" in messages[1]["content"]

    def test_get_prompt_version(self):
        """Test prompt version string generation."""
        from app.llm.prompts import get_prompt_version

        version_str = get_prompt_version("smoke_test", "v1")
        assert version_str == "smoke_test@v1"