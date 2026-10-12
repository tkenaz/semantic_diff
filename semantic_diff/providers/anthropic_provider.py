"""
Adapter: Anthropic Messages API.
"""

import anthropic

from semantic_diff.providers.base import (
    Completion,
    ProviderError,
    RateLimitError,
    TransientError,
    parse_retry_after,
)


class AnthropicProvider:
    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client = client
        self.model = model

    def complete(self, prompt: str, *, max_tokens: int) -> Completion:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError as e:
            raise RateLimitError(
                str(e), parse_retry_after(e.response.headers.get("retry-after"))
            ) from e
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            raise TransientError(str(e)) from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise TransientError(f"{e.status_code}: {e}") from e
            raise ProviderError(f"{e.status_code}: {e}") from e

        # content[0] is not guaranteed to be text (thinking blocks come first)
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise ProviderError("Model response contains no text block")
        return Completion(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
