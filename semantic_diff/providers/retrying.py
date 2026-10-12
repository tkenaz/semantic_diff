"""
Retry decorator over any LLMProvider. The only place retry policy lives -
SDK clients are built with their own retries switched off.
"""

import logging
import os
import random
import time
from typing import Callable, Optional

from semantic_diff.providers.base import (
    Completion,
    LLMProvider,
    ProviderError,
    RateLimitError,
    TransientError,
)

logger = logging.getLogger(__name__)


class RetryingProvider:
    def __init__(
        self,
        inner: LLMProvider,
        *,
        max_retries: Optional[int] = None,
        base_delay: float = 1.0,
        max_total_wait: Optional[float] = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ):
        self.inner = inner
        max_retries = (
            max_retries
            if max_retries is not None
            else int(os.getenv("SEMANTIC_DIFF_MAX_RETRIES", "3"))
        )
        if max_retries < 1:
            raise ValueError(f"max_retries must be at least 1 (one attempt), got {max_retries}")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_total_wait = (
            max_total_wait
            if max_total_wait is not None
            else float(os.getenv("SEMANTIC_DIFF_MAX_WAIT", "30.0"))
        )
        self._sleep = sleep
        self._jitter = jitter

    @property
    def model(self) -> str:
        return self.inner.model

    def complete(self, prompt: str, *, max_tokens: int) -> Completion:
        waited = 0.0
        last_error: Optional[TransientError] = None

        for attempt in range(self.max_retries):
            try:
                return self.inner.complete(prompt, max_tokens=max_tokens)
            except TransientError as e:
                last_error = e
                if attempt == self.max_retries - 1:
                    break
                delay = self._delay(e, attempt)
                if waited + delay > self.max_total_wait:
                    logger.warning(f"Retry would exceed max_total_wait ({self.max_total_wait}s)")
                    break
                logger.warning(f"{e}; retry {attempt + 1}/{self.max_retries} in {delay:.1f}s")
                self._sleep(delay)
                waited += delay

        raise ProviderError(
            f"LLM call failed after {attempt + 1} attempts (waited {waited:.1f}s): {last_error}"
        )

    def _delay(self, error: TransientError, attempt: int) -> float:
        if isinstance(error, RateLimitError) and error.retry_after is not None:
            return error.retry_after
        backoff = self.base_delay * (2**attempt)
        return backoff * (1 + self._jitter(0.1, 0.3))
