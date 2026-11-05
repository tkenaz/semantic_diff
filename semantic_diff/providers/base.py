"""
The LLM port: what the analyzer needs from any model backend.

Adapters translate their vendor SDK into these types - responses into
Completion, exceptions into the error hierarchy below - so nothing outside an
adapter knows which protocol is spoken.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, Sequence, Tuple, Union


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    truncated: bool = False  # the model stopped at max_tokens, mid-answer


class ProviderError(Exception):
    """A provider call failed and retrying will not help."""


class ModelUnavailableError(ProviderError):
    """404: the endpoint does not serve this model - retired, not enabled for the key, or a
    wrong base URL. Never retried and never swapped for another model: a different model
    gives different results, so the choice stays with the user."""

    def __init__(self, model: str, detail: str):
        super().__init__(
            f"model {model} is not available at this endpoint (retired, not enabled for your "
            "key, or a wrong base URL). Set SEMANTIC_DIFF_MODEL or --model to one that is; "
            "reports from another model are not comparable with earlier ones. "
            f"The endpoint said: {detail}"
        )
        self.model = model


class TransientError(ProviderError):
    """Timeout, connection drop or 5xx - worth retrying."""


class RateLimitError(TransientError):
    """429. retry_after is the server's hint in seconds, when it gave a usable one."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class RetriesExhaustedError(ProviderError):
    """A transient failure outlasted the retry policy. rate_limited tells a 429 that
    never cleared (a quota or concurrency problem) from timeouts and 5xx (an outage)."""

    def __init__(self, message: str, *, rate_limited: bool, attempts: int, waited: float):
        super().__init__(message)
        self.rate_limited = rate_limited
        self.attempts = attempts
        self.waited = waited


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


def parse_retry_after(value: Optional[str], *, now: Optional[float] = None) -> Optional[float]:
    """Retry-After in seconds: delta-seconds or an HTTP-date (RFC 9110 10.2.3).
    None when the value is missing or unusable; a date in the past means 0."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if moment.tzinfo is None:  # HTTP-dates are GMT by definition
            moment = moment.replace(tzinfo=timezone.utc)
        seconds = moment.timestamp() - (time.time() if now is None else now)
    if seconds != seconds or seconds in (float("inf"), float("-inf")):  # NaN, inf
        return None
    return max(seconds, 0.0)


# Anthropic: one reset timestamp (RFC 3339) per limit; the exhausted limit has remaining 0
_ANTHROPIC_LIMITS = ("requests", "tokens", "input-tokens", "output-tokens")


def retry_after_from_headers(
    headers: Mapping[str, str], *, now: Optional[float] = None
) -> Optional[float]:
    """The server's wait hint on a 429, in seconds, from the most precise header present:
    retry-after-ms (OpenAI-style gateways), retry-after, then Anthropic's
    anthropic-ratelimit-<limit>-reset of whichever limit is exhausted."""
    ms = parse_retry_after(headers.get("retry-after-ms"), now=now)
    if ms is not None:
        return ms / 1000.0
    seconds = parse_retry_after(headers.get("retry-after"), now=now)
    if seconds is not None:
        return seconds

    resets = []
    for limit in _ANTHROPIC_LIMITS:
        if headers.get(f"anthropic-ratelimit-{limit}-remaining") != "0":
            continue
        reset = _rfc3339(headers.get(f"anthropic-ratelimit-{limit}-reset"))
        if reset is not None:
            resets.append(reset - (time.time() if now is None else now))
    return max(0.0, max(resets)) if resets else None


def _rfc3339(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()
