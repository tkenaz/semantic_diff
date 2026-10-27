"""
Composition root for providers: config (env) -> adapter, wrapped in retries.
Adding a protocol = one adapter module + one entry in PROVIDERS.
"""

import os
from typing import Callable, Dict, Optional

from dotenv import find_dotenv, load_dotenv

from semantic_diff.providers.base import LLMProvider
from semantic_diff.providers.retrying import RetryingProvider

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
# Long answers on big merge requests take minutes. An explicit timeout also lifts the
# Anthropic SDK's refusal of large non-streaming max_tokens.
CLIENT_TIMEOUT_SECONDS = 900.0


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} not found in environment")
    return value


def _anthropic(model: Optional[str]) -> LLMProvider:
    import anthropic

    from semantic_diff.providers.anthropic_provider import AnthropicProvider

    client = anthropic.Anthropic(
        api_key=_require("ANTHROPIC_API_KEY"), max_retries=0, timeout=CLIENT_TIMEOUT_SECONDS
    )
    return AnthropicProvider(client=client, model=model or DEFAULT_ANTHROPIC_MODEL)


def _openai_compat(model: Optional[str]) -> LLMProvider:
    try:
        import openai
    except ImportError as e:
        raise ValueError("Provider 'openai' needs: pip install 'semantic-diff[openai]'") from e

    from semantic_diff.providers.openai_compat import OpenAICompatProvider

    client = openai.OpenAI(
        api_key=_require("SEMANTIC_DIFF_API_KEY"),
        base_url=_require("SEMANTIC_DIFF_BASE_URL"),
        max_retries=0,
        timeout=CLIENT_TIMEOUT_SECONDS,
    )
    # No default model: model ids differ per gateway, a guess would just 404.
    if not model:
        raise ValueError("SEMANTIC_DIFF_MODEL not found in environment (required for 'openai')")
    return OpenAICompatProvider(client=client, model=model)


PROVIDERS: Dict[str, Callable[[Optional[str]], LLMProvider]] = {
    "anthropic": _anthropic,
    "openai": _openai_compat,
}


def build_provider(model: Optional[str] = None, *, load_env: bool = True) -> RetryingProvider:
    if load_env:
        # usecwd: the .env of the repository being analyzed; the default
        # searches upward from this module, i.e. from site-packages
        load_dotenv(find_dotenv(usecwd=True))
    name = os.getenv("SEMANTIC_DIFF_PROVIDER", "anthropic")
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider '{name}'. Known: {', '.join(PROVIDERS)}")
    return RetryingProvider(PROVIDERS[name](model or os.getenv("SEMANTIC_DIFF_MODEL")))
