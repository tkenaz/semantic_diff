"""
Adapter: OpenAI Chat Completions protocol, for any compatible gateway
(e.g. T-Systems AIFS, vLLM, LiteLLM, OpenAI itself).
"""

import openai

from semantic_diff.providers.base import (
    Completion,
    ProviderError,
    RateLimitError,
    TransientError,
    parse_retry_after,
)


class OpenAICompatProvider:
    def __init__(self, client: openai.OpenAI, model: str):
        self.client = client
        self.model = model

    def complete(self, prompt: str, *, max_tokens: int) -> Completion:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except openai.RateLimitError as e:
            raise RateLimitError(
                str(e), parse_retry_after(e.response.headers.get("retry-after"))
            ) from e
        except (openai.APITimeoutError, openai.APIConnectionError) as e:
            raise TransientError(str(e)) from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise TransientError(f"{e.status_code}: {e}") from e
            raise ProviderError(f"{e.status_code}: {e}") from e

        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise ProviderError("Model response contains no text")
        usage = response.usage
        return Completion(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
