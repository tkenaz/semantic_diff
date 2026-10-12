"""
LLM providers: a port (LLMProvider), vendor adapters, retries and the factory.
"""

from semantic_diff.providers.anthropic_provider import AnthropicProvider
from semantic_diff.providers.base import (
    Completion,
    LLMProvider,
    ProviderError,
    RateLimitError,
    TransientError,
)
from semantic_diff.providers.factory import PROVIDERS, build_provider
from semantic_diff.providers.retrying import RetryingProvider

__all__ = [
    "PROVIDERS",
    "AnthropicProvider",
    "Completion",
    "LLMProvider",
    "OpenAICompatProvider",
    "ProviderError",
    "RateLimitError",
    "RetryingProvider",
    "TransientError",
    "build_provider",
]


def __getattr__(name):
    # Lazy: importing the package must not require the optional `openai` extra.
    if name == "OpenAICompatProvider":
        from semantic_diff.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
