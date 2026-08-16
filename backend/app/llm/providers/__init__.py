"""Provider factory for creating LLM provider instances."""

from app.core.settings import settings
from app.llm.providers.base import LLMProvider
from app.llm.providers.openai import MockProvider, OpenAIProvider


def get_provider() -> LLMProvider:
    """Get the configured LLM provider instance."""
    provider_name = settings.llm_provider.lower()

    if provider_name == "openai":
        return OpenAIProvider()
    elif provider_name == "mock":
        return MockProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")