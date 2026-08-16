"""LLM Model Gateway — centralized interface for all LLM calls.

This module provides the single, centralized interface every AI feature calls through.
No feature module should ever call a model provider's SDK directly.

Key features:
- Provider abstraction (model_tier -> actual model mapping)
- Cost/token logging to llm_calls table
- Prompt versioning
- Structured-output validation with retry
- Response caching via Redis
- Prompt-injection safety via build_messages()
"""

import json
import time
import uuid
from collections.abc import Callable
from typing import Any, Optional, TypeVar

import redis.asyncio as redis
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.models import LLMCall, LLMCallStatus
from app.db.session import async_session_factory
from app.llm.providers import get_provider
from app.llm.providers.base import LLMResponse, TokenUsage

T = TypeVar("T", bound=BaseModel)
SessionFactory = Callable[[], AsyncSession]


class ModelGateway:
    """Centralized gateway for all LLM interactions."""

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        session_factory: SessionFactory | None = None,
    ):
        self.provider = get_provider()
        self.redis = redis_client
        self.session_factory: SessionFactory = session_factory or async_session_factory

        # Model tier to actual model name mapping
        self.model_tiers = {
            "fast": settings.llm_default_model_fast,
            "reasoning": settings.llm_default_model_reasoning,
            "vision": settings.llm_default_model_vision,
        }

    def _resolve_model(self, model_tier: str) -> str:
        """Resolve model tier to actual model name."""
        return self.model_tiers.get(model_tier, settings.llm_default_model_fast)

    def _generate_cache_key(self, cache_key: str) -> str:
        """Generate a Redis cache key with prefix."""
        return f"llm_cache:{cache_key}"

    async def _get_cached(self, cache_key: str) -> Optional[dict[str, Any]]:
        """Get cached response from Redis."""
        if not self.redis:
            return None
        try:
            data = await self.redis.get(self._generate_cache_key(cache_key))
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None

    async def _set_cached(self, cache_key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        """Set cached response in Redis."""
        if not self.redis:
            return
        try:
            ttl = ttl or settings.llm_cache_ttl_seconds
            await self.redis.set(
                self._generate_cache_key(cache_key),
                json.dumps(value),
                ex=ttl,
            )
        except Exception:
            pass

    async def _log_call(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        task_type: str,
        model_tier: str,
        model_name: str,
        prompt_version: Optional[str],
        correlation_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost_estimate: float,
        status: LLMCallStatus,
    ) -> None:
        """Log an LLM call to the database."""
        call = LLMCall(
            org_id=org_id,
            task_type=task_type,
            model_tier=model_tier,
            model_name=model_name,
            prompt_version=prompt_version,
            correlation_id=correlation_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_estimate=cost_estimate,
            status=status,
        )
        session.add(call)
        await session.commit()

    async def complete(
        self,
        *,
        org_id: uuid.UUID,
        task_type: str,
        prompt: str | list[dict[str, str]],
        model_tier: str = "fast",
        response_schema: Optional[type[T]] = None,
        cache_key: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        prompt_version: Optional[str] = None,
        correlation_id: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> T | str:
        """Complete a prompt with optional structured output and caching.

        Args:
            org_id: Organization ID for RLS and cost tracking.
            task_type: Type of task (e.g., "requirement_extraction", "draft_generation").
            prompt: Either a string (user message) or list of message dicts.
            model_tier: Model tier ("fast", "reasoning", "vision").
            response_schema: Optional Pydantic model for structured output.
            cache_key: Optional cache key for response caching.
            cache_ttl: Optional cache TTL in seconds.
            prompt_version: Optional prompt version for traceability.
            correlation_id: Optional correlation ID for tracing.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            If response_schema provided: validated Pydantic model instance.
            Otherwise: raw string response.
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        model_name = self._resolve_model(model_tier)
        start_time = time.time()

        # Check cache first
        if cache_key:
            cached = await self._get_cached(cache_key)
            if cached:
                latency_ms = int((time.time() - start_time) * 1000)
                async with self.session_factory() as session:
                    await self._log_call(
                        session=session,
                        org_id=org_id,
                        task_type=task_type,
                        model_tier=model_tier,
                        model_name=model_name,
                        prompt_version=prompt_version,
                        correlation_id=correlation_id,
                        input_tokens=0,
                        output_tokens=0,
                        latency_ms=latency_ms,
                        cost_estimate=0.0,
                        status=LLMCallStatus.CACHE_HIT,
                    )
                if response_schema:
                    return response_schema.model_validate(cached["content"])
                return cached["content"]

        # Build messages
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = prompt

        # Call provider with retry for structured output
        last_error: Optional[Exception] = None
        for attempt in range(2):  # 1 retry = 2 attempts total
            try:
                response: LLMResponse = await self.provider.complete(
                    messages=messages,
                    model=model_name,
                    response_schema=response_schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                latency_ms = int((time.time() - start_time) * 1000)
                cost_estimate = self.provider.estimate_cost(response.usage, model_name)

                # Validate structured output if schema provided
                if response_schema:
                    try:
                        validated = response_schema.model_validate_json(response.content)
                        content = validated
                    except ValidationError as e:
                        last_error = e
                        if attempt == 0:
                            # Retry once with a correction hint
                            correction_msg = (
                                f"Previous response failed validation: {e}. "
                                "Please return valid JSON matching the schema."
                            )
                            messages.append({"role": "assistant", "content": response.content})
                            messages.append({"role": "user", "content": correction_msg})
                            continue
                        else:
                            # Validation failed after retry - log and raise
                            async with self.session_factory() as session:
                                await self._log_call(
                                    session=session,
                                    org_id=org_id,
                                    task_type=task_type,
                                    model_tier=model_tier,
                                    model_name=model_name,
                                    prompt_version=prompt_version,
                                    correlation_id=correlation_id,
                                    input_tokens=response.usage.input_tokens,
                                    output_tokens=response.usage.output_tokens,
                                    latency_ms=latency_ms,
                                    cost_estimate=cost_estimate,
                                    status=LLMCallStatus.FAILED,
                                )
                            raise
                else:
                    content = response.content

                # Log success
                async with self.session_factory() as session:
                    await self._log_call(
                        session=session,
                        org_id=org_id,
                        task_type=task_type,
                        model_tier=model_tier,
                        model_name=model_name,
                        prompt_version=prompt_version,
                        correlation_id=correlation_id,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        latency_ms=latency_ms,
                        cost_estimate=cost_estimate,
                        status=LLMCallStatus.SUCCESS,
                    )

                # Cache result
                if cache_key:
                    await self._set_cached(cache_key, {"content": content}, cache_ttl)

                return content

            except ValidationError:
                # Already logged in the inner block, just re-raise
                raise
            except Exception as e:
                last_error = e
                if attempt == 0:
                    continue
                # Log failure on final attempt (for non-ValidationError exceptions)
                latency_ms = int((time.time() - start_time) * 1000)
                async with self.session_factory() as session:
                    await self._log_call(
                        session=session,
                        org_id=org_id,
                        task_type=task_type,
                        model_tier=model_tier,
                        model_name=model_name,
                        prompt_version=prompt_version,
                        correlation_id=correlation_id,
                        input_tokens=0,
                        output_tokens=0,
                        latency_ms=latency_ms,
                        cost_estimate=0.0,
                        status=LLMCallStatus.FAILED,
                    )
                raise

        # Should not reach here
        raise last_error or RuntimeError("Unexpected error in complete()")

    async def embed(
        self,
        *,
        org_id: uuid.UUID,
        task_type: str,
        texts: list[str],
        model_tier: str = "fast",
        cache_key: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        prompt_version: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            org_id: Organization ID for RLS and cost tracking.
            task_type: Type of task (e.g., "embedding_generation").
            texts: List of texts to embed.
            model_tier: Model tier (currently only "fast" supported for embeddings).
            cache_key: Optional cache key for response caching.
            cache_ttl: Optional cache TTL in seconds.
            prompt_version: Optional prompt version for traceability.
            correlation_id: Optional correlation ID for tracing.

        Returns:
            List of embedding vectors.
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        model_name = self._resolve_model(model_tier)
        start_time = time.time()

        # Check cache first
        if cache_key:
            cached = await self._get_cached(cache_key)
            if cached:
                latency_ms = int((time.time() - start_time) * 1000)
                async with self.session_factory() as session:
                    await self._log_call(
                        session=session,
                        org_id=org_id,
                        task_type=task_type,
                        model_tier=model_tier,
                        model_name=model_name,
                        prompt_version=prompt_version,
                        correlation_id=correlation_id,
                        input_tokens=0,
                        output_tokens=0,
                        latency_ms=latency_ms,
                        cost_estimate=0.0,
                        status=LLMCallStatus.CACHE_HIT,
                    )
                return cached["content"]

        # Call provider
        try:
            embeddings = await self.provider.embed(texts=texts, model=model_name)

            # Estimate token usage (rough approximation)
            total_chars = sum(len(t) for t in texts)
            input_tokens = total_chars // 4  # rough approximation

            latency_ms = int((time.time() - start_time) * 1000)
            usage = TokenUsage(input_tokens=input_tokens, output_tokens=0, total_tokens=input_tokens)
            cost_estimate = self.provider.estimate_cost(usage, model_name)

            # Log success
            async with self.session_factory() as session:
                await self._log_call(
                    session=session,
                    org_id=org_id,
                    task_type=task_type,
                    model_tier=model_tier,
                    model_name=model_name,
                    prompt_version=prompt_version,
                    correlation_id=correlation_id,
                    input_tokens=input_tokens,
                    output_tokens=0,
                    latency_ms=latency_ms,
                    cost_estimate=cost_estimate,
                    status=LLMCallStatus.SUCCESS,
                )

            # Cache result
            if cache_key:
                await self._set_cached(cache_key, {"content": embeddings}, cache_ttl)

            return embeddings

        except Exception:
            latency_ms = int((time.time() - start_time) * 1000)
            async with self.session_factory() as session:
                await self._log_call(
                    session=session,
                    org_id=org_id,
                    task_type=task_type,
                    model_tier=model_tier,
                    model_name=model_name,
                    prompt_version=prompt_version,
                    correlation_id=correlation_id,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=latency_ms,
                    cost_estimate=0.0,
                    status=LLMCallStatus.FAILED,
                )
            raise


def build_messages(
    system_instructions: str,
    untrusted_document_content: str,
    user_task: str,
) -> list[dict[str, str]]:
    """Build messages with prompt-injection safety.

    Ingested document content is ALWAYS untrusted data (adversarial-by-default).
    This function enforces the architectural rule that document content goes in
    a clearly delimited data/context role, never string-concatenated into
    system instructions.

    Args:
        system_instructions: The system prompt with instructions for the model.
        untrusted_document_content: The document content to analyze (untrusted).
        user_task: The specific task for the model to perform.

    Returns:
        List of message dicts for the LLM API.

    Example:
        >>> messages = build_messages(
        ...     system_instructions="You are an RFP analyzer.",
        ...     untrusted_document_content="<document>...RFP text...</document>",
        ...     user_task="Extract all requirements from the document."
        ... )
    """
    return [
        {"role": "system", "content": system_instructions},
        {"role": "user", "content": f"<document_content>\n{untrusted_document_content}\n</document_content>"},
        {"role": "user", "content": user_task},
    ]