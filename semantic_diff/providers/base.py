"""
The LLM port: what the analyzer needs from any model backend.

Adapters translate their vendor SDK into these types - responses into
Completion, exceptions into the error hierarchy below - so nothing outside an
adapter knows which protocol is spoken.
"""

from dataclasses import dataclass
from typing import Optional, Protocol


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


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Retry-After in seconds; the HTTP-date form is ignored (backoff applies instead)."""
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
