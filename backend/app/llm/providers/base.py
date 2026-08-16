"""LLM provider adapter interface and implementations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel


@dataclass
class TokenUsage:
    """Token usage from an LLM call."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class LLMResponse:
    """Response from an LLM call."""

    content: str
    usage: TokenUsage
    model: str
    raw_response: Any


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Complete a chat conversation.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            model: Model name to use.
            response_schema: Optional Pydantic model for structured output.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            LLMResponse with content, usage, and metadata.
        """
        pass

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of texts to embed.
            model: Embedding model name.

        Returns:
            List of embedding vectors (list of floats).
        """
        pass

    @abstractmethod
    def estimate_cost(self, usage: TokenUsage, model: str) -> float:
        """Estimate cost in USD for a given token usage and model.

        Args:
            usage: Token usage from the call.
            model: Model name used.

        Returns:
            Estimated cost in USD.
        """
        pass