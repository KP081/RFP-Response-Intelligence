"""OpenAI provider implementation."""

import json
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.settings import settings
from app.llm.providers.base import LLMProvider, LLMResponse, TokenUsage


class OpenAIProvider(LLMProvider):
    """OpenAI API provider implementation."""

    def __init__(self, api_key: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key or settings.llm_api_key)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Complete a chat conversation using OpenAI API."""

        if response_schema:
            # Use structured output via function calling
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "structured_output",
                        "description": "Return structured output matching the schema",
                        "parameters": response_schema.model_json_schema(),
                    },
                }
            ]
            tool_choice = {"type": "function", "function": {"name": "structured_output"}}

            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Extract the function call arguments
            if response.choices[0].message.tool_calls:
                function_args = response.choices[0].message.tool_calls[0].function.arguments
                content = function_args
            else:
                content = response.choices[0].message.content or "{}"
        else:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""

        usage = TokenUsage(
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
        )

        return LLMResponse(
            content=content,
            usage=usage,
            model=response.model,
            raw_response=response.model_dump(),
        )

    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        """Generate embeddings using OpenAI API."""
        response = await self.client.embeddings.create(
            model=model,
            input=texts,
        )
        return [data.embedding for data in response.data]

    def estimate_cost(self, usage: TokenUsage, model: str) -> float:
        """Estimate cost in USD for OpenAI models."""
        # Pricing per 1M tokens (as of 2024)
        pricing = {
            "gpt-4o": {"input": 5.00, "output": 15.00},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4-turbo": {"input": 10.00, "output": 30.00},
            "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
            "text-embedding-3-small": {"input": 0.02, "output": 0.0},
            "text-embedding-3-large": {"input": 0.13, "output": 0.0},
        }

        model_pricing = pricing.get(model, {"input": 0.0, "output": 0.0})
        input_cost = (usage.input_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (usage.output_tokens / 1_000_000) * model_pricing["output"]
        return input_cost + output_cost


class MockProvider(LLMProvider):
    """Mock provider for testing and local development."""

    def __init__(self):
        self.call_count = 0
        self.last_messages: list[dict[str, str]] = []
        self.last_model: str = ""
        self.last_response_schema: Optional[type[BaseModel]] = None

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Return a mock response."""
        self.call_count += 1
        self.last_messages = messages
        self.last_model = model
        self.last_response_schema = response_schema

        if response_schema:
            # Return a mock structured response
            schema = response_schema.model_json_schema()
            # Generate a simple mock based on schema properties
            mock_data = {}
            for prop_name, prop_info in schema.get("properties", {}).items():
                prop_type = prop_info.get("type", "string")
                if prop_type == "string":
                    mock_data[prop_name] = f"mock_{prop_name}"
                elif prop_type == "integer":
                    mock_data[prop_name] = 42
                elif prop_type == "boolean":
                    mock_data[prop_name] = True
                elif prop_type == "array":
                    mock_data[prop_name] = []
                else:
                    mock_data[prop_name] = "mock"
            content = json.dumps(mock_data)
        else:
            content = "Mock response from provider"

        usage = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)

        return LLMResponse(
            content=content,
            usage=usage,
            model=model,
            raw_response={"mock": True},
        )

    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        """Return mock embeddings."""
        self.call_count += 1
        # Return 1536-dimensional mock embeddings
        return [[0.1] * 1536 for _ in texts]

    def estimate_cost(self, usage: TokenUsage, model: str) -> float:
        """Return zero cost for mock."""
        return 0.0