"""
LLM providers: a port (LLMProvider), vendor adapters, retries and the factory.
"""

from semantic_diff.providers.base import (
    AssistantMessage,
    Completion,
    LLMProvider,
    Message,
    ModelUnavailableError,
    ProviderError,
    RateLimitError,
    StopReason,
    ToolCall,
    ToolCallingProvider,
    ToolResult,
    ToolSpec,
    TransientError,
    Turn,
    UserMessage,
)
from semantic_diff.providers.factory import PROVIDERS, build_provider
from semantic_diff.providers.retrying import RetryingProvider

# The vendor adapters are importable by name (see __getattr__) but kept out of
# __all__: `import *` must work without the optional `anthropic` and `openai`
# extras, so an install that leaves a vendor SDK out cannot reach it by accident.
__all__ = [
    "PROVIDERS",
    "AssistantMessage",
    "Completion",
    "LLMProvider",
    "Message",
    "ModelUnavailableError",
    "ProviderError",
    "RateLimitError",
    "RetryingProvider",
    "StopReason",
    "ToolCall",
    "ToolCallingProvider",
    "ToolResult",
    "ToolSpec",
    "TransientError",
    "Turn",
    "UserMessage",
    "build_provider",
]


def __getattr__(name):
    # Lazy: importing the package must not require an optional vendor extra.
    if name == "AnthropicProvider":
        from semantic_diff.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider
    if name == "OpenAICompatProvider":
        from semantic_diff.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
