"""
Retry decorator over any LLMProvider. The only place retry policy lives -
SDK clients are built with their own retries switched off.

Defaults are sized for CI: a shared key under load gets 429s for tens of
seconds, not milliseconds, so a review should wait the window out (the
server's hint when it gives one, exponential backoff with jitter when not)
rather than fail a pipeline a few seconds in.
"""

import logging
import os
import random
import time
from typing import Callable, Optional, Sequence, TypeVar

from semantic_diff.providers.base import (
    Completion,
    LLMProvider,
    Message,
    RateLimitError,
    RetriesExhaustedError,
    ToolSpec,
    TransientError,
    Turn,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)

MAX_RETRIES_VARIABLE = "SEMANTIC_DIFF_MAX_RETRIES"
MAX_WAIT_VARIABLE = "SEMANTIC_DIFF_MAX_WAIT"
DEFAULT_MAX_RETRIES = 5  # retries after the first attempt
DEFAULT_MAX_TOTAL_WAIT = 180.0  # seconds slept over all retries of one call
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 60.0  # one backoff step, before jitter; rate-limit windows are per minute


class RetryingProvider:
    def __init__(
        self,
        inner: LLMProvider,
        *,
        max_retries: Optional[int] = None,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        max_total_wait: Optional[float] = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ):
        self.inner = inner
        if max_retries is None:
            max_retries = _env(MAX_RETRIES_VARIABLE, int, DEFAULT_MAX_RETRIES)
        if max_retries < 0:
            raise ValueError(f"max_retries must be 0 or more, got {max_retries}")
        if max_total_wait is None:
            max_total_wait = _env(MAX_WAIT_VARIABLE, float, DEFAULT_MAX_TOTAL_WAIT)
        if max_total_wait < 0:
            raise ValueError(f"max_total_wait must be 0 or more, got {max_total_wait}")
        self.max_retries = max_retries
        self.max_total_wait = max_total_wait
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep
        self._jitter = jitter

    @property
    def model(self) -> str:
        return self.inner.model

    def complete(self, prompt: str, *, max_tokens: int) -> Completion:
        return self._with_retries(lambda: self.inner.complete(prompt, max_tokens=max_tokens))

    def converse(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        max_tokens: int,
    ) -> Turn:
        return self._with_retries(
            lambda: self.inner.converse(system, messages, tools, max_tokens=max_tokens)
        )

    def _with_retries(self, call: Callable[[], T]) -> T:
        waited = 0.0
        attempts = 0
        stopped_by = "max_retries"

        while True:
            attempts += 1
            try:
                return call()
            except TransientError as e:
                last_error = e
            if attempts > self.max_retries:
                break
            delay = self._delay(last_error, attempts - 1)
            if waited + delay > self.max_total_wait:
                logger.warning(f"Retry would exceed max_total_wait ({self.max_total_wait:g}s)")
                stopped_by = "max_total_wait"
                break
            logger.warning(f"{last_error}; retry {attempts}/{self.max_retries} in {delay:.1f}s")
            self._sleep(delay)
            waited += delay

        raise _exhausted(last_error, attempts, waited, stopped_by, self.max_total_wait)

    def _delay(self, error: TransientError, retry: int) -> float:
        """The server's hint as given; otherwise base * 2^retry, capped, plus 10-30% jitter
        so jobs sharing a key do not retry in lockstep."""
        if isinstance(error, RateLimitError) and error.retry_after is not None:
            return error.retry_after
        backoff = min(self.base_delay * (2**retry), self.max_delay)
        return backoff * (1 + self._jitter(0.1, 0.3))


def _exhausted(
    error: TransientError, attempts: int, waited: float, stopped_by: str, budget: float
) -> RetriesExhaustedError:
    rate_limited = isinstance(error, RateLimitError)
    tried = f"{attempts} attempts, waited {waited:.1f}s"
    if stopped_by == "max_total_wait":
        tried += f"; the next wait would pass the {budget:g}s budget"
    if rate_limited:
        hint = (
            f" (the API asked to wait {error.retry_after:.0f}s)"
            if error.retry_after is not None
            else ""
        )
        message = (
            f"Rate limited by the LLM API (HTTP 429) after {tried}{hint}. "
            f"The key's quota is exhausted for now: retry later, run fewer jobs on this key, "
            f"or allow longer waits with --max-retry-wait / {MAX_WAIT_VARIABLE} and "
            f"--max-retries / {MAX_RETRIES_VARIABLE}. Last response: {error}"
        )
    else:
        message = f"LLM API call failed after {tried}: {error}"
    return RetriesExhaustedError(
        message, rate_limited=rate_limited, attempts=attempts, waited=waited
    )


def _env(name: str, kind, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return kind(value)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {value!r}") from None
