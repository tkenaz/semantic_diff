"""
The LLM port: what the analyzer needs from any model backend.

Adapters translate their vendor SDK into these types - responses into
Completion, exceptions into the error hierarchy below - so nothing outside an
adapter knows which protocol is spoken.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, Sequence, Tuple, Union


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


class ProviderError(Exception):
    """A provider call failed and retrying will not help."""


class TransientError(ProviderError):
    """Timeout, connection drop or 5xx - worth retrying."""


class RateLimitError(TransientError):
    """429. retry_after is the server's hint in seconds, when it gave a usable one."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMProvider(Protocol):
    model: str

    def complete(self, prompt: str, *, max_tokens: int) -> Completion: ...


# --- tool calling: a multi-turn conversation in which the model calls tools ---


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]  # JSON schema of the arguments object


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Optional[Mapping[str, Any]]  # None when raw_arguments is not a JSON object
    raw_arguments: str


@dataclass(frozen=True)
class UserMessage:
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    text: str
    tool_calls: Tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


Message = Union[UserMessage, AssistantMessage, ToolResult]


class StopReason(str, Enum):
    END = "end"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"


@dataclass(frozen=True)
class Turn:
    text: str
    tool_calls: Tuple[ToolCall, ...]
    stop_reason: StopReason
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def as_message(self) -> AssistantMessage:
        return AssistantMessage(self.text, self.tool_calls)


class ToolCallingProvider(Protocol):
    model: str

    def converse(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        max_tokens: int,
    ) -> Turn: ...


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Retry-After in seconds; the HTTP-date form is ignored (backoff applies instead)."""
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
