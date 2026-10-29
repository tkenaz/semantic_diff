"""
Tests for LLM providers - the port the analyzer talks to, its vendor adapters,
the retry decorator and the factory that picks an adapter from config.

Adapters are tested against real SDK types (responses and exceptions), only the
network client is faked.
"""

import os
from unittest.mock import Mock, patch

import anthropic
import httpx
import openai
import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, Usage
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice

from semantic_diff.providers import (
    AnthropicProvider,
    Completion,
    ModelUnavailableError,
    OpenAICompatProvider,
    ProviderError,
    RateLimitError,
    RetryingProvider,
    TransientError,
    build_provider,
)

REQUEST = httpx.Request("POST", "https://llm.example/v1")


def _http(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers or {}, request=REQUEST)


def _anthropic_message(
    *blocks, input_tokens=11, output_tokens=7, stop_reason="end_turn"
) -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-test",
        content=list(blocks),
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _chat_completion(
    content, prompt_tokens=13, completion_tokens=5, finish_reason="stop"
) -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-1",
        object="chat.completion",
        created=0,
        model="claude-sonnet-4.6",
        choices=[
            Choice(
                index=0,
                finish_reason=finish_reason,
                message=ChatCompletionMessage(role="assistant", content=content),
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


# --- vendor error factories, one row per (vendor, kind) ---------------------

VENDOR_ERRORS = {
    "anthropic": {
        "rate_limit": lambda headers=None: anthropic.RateLimitError(
            "slow down", response=_http(429, headers), body={}
        ),
        "timeout": lambda: anthropic.APITimeoutError(request=REQUEST),
        "connection": lambda: anthropic.APIConnectionError(request=REQUEST),
        "server": lambda: anthropic.InternalServerError("boom", response=_http(500), body={}),
        "client": lambda: anthropic.BadRequestError("bad", response=_http(400), body={}),
        "client_499": lambda: anthropic.APIStatusError("odd", response=_http(499), body={}),
        "not_found": lambda: anthropic.NotFoundError(
            "model x retired, use y", response=_http(404), body={}
        ),
    },
    "openai": {
        "rate_limit": lambda headers=None: openai.RateLimitError(
            "slow down", response=_http(429, headers), body={}
        ),
        "timeout": lambda: openai.APITimeoutError(request=REQUEST),
        "connection": lambda: openai.APIConnectionError(request=REQUEST),
        "server": lambda: openai.InternalServerError("boom", response=_http(500), body={}),
        "client": lambda: openai.BadRequestError("bad", response=_http(400), body={}),
        "client_499": lambda: openai.APIStatusError("odd", response=_http(499), body={}),
        "not_found": lambda: openai.NotFoundError(
            "model x retired, use y", response=_http(404), body={}
        ),
    },
}


def _adapter(vendor: str, client):
    if vendor == "anthropic":
        return AnthropicProvider(client=client, model="m")
    return OpenAICompatProvider(client=client, model="m")


def _failing_client(vendor: str, error: Exception) -> Mock:
    client = Mock()
    if vendor == "anthropic":
        client.messages.create.side_effect = error
    else:
        client.chat.completions.create.side_effect = error
    return client


class TestAnthropicProvider:
    def test_maps_message_to_completion(self):
        client = Mock()
        client.messages.create.return_value = _anthropic_message(
            TextBlock(type="text", text='{"ok": true}'), input_tokens=11, output_tokens=7
        )
        provider = AnthropicProvider(client=client, model="claude-x")

        result = provider.complete("prompt", max_tokens=123)

        assert result == Completion(text='{"ok": true}', input_tokens=11, output_tokens=7)
        client.messages.create.assert_called_once_with(
            model="claude-x",
            max_tokens=123,
            messages=[{"role": "user", "content": "prompt"}],
        )

    def test_takes_first_text_block_not_first_block(self):
        client = Mock()
        client.messages.create.return_value = _anthropic_message(
            ThinkingBlock(type="thinking", thinking="hmm", signature="sig"),
            TextBlock(type="text", text="answer"),
            TextBlock(type="text", text="second"),
        )

        result = AnthropicProvider(client=client, model="m").complete("p", max_tokens=1)

        assert result.text == "answer"

    def test_no_text_block_is_provider_error(self):
        client = Mock()
        client.messages.create.return_value = _anthropic_message(
            ThinkingBlock(type="thinking", thinking="hmm", signature="sig")
        )

        with pytest.raises(ProviderError, match="no text"):
            AnthropicProvider(client=client, model="m").complete("p", max_tokens=1)

    def test_exposes_model(self):
        assert AnthropicProvider(client=Mock(), model="claude-x").model == "claude-x"


class TestOpenAICompatProvider:
    def test_maps_chat_completion_to_completion(self):
        client = Mock()
        client.chat.completions.create.return_value = _chat_completion(
            '{"ok": true}', prompt_tokens=13, completion_tokens=5
        )
        provider = OpenAICompatProvider(client=client, model="claude-sonnet-4.6")

        result = provider.complete("prompt", max_tokens=321)

        assert result == Completion(text='{"ok": true}', input_tokens=13, output_tokens=5)
        client.chat.completions.create.assert_called_once_with(
            model="claude-sonnet-4.6",
            max_tokens=321,
            messages=[{"role": "user", "content": "prompt"}],
        )

    def test_empty_content_is_provider_error(self):
        client = Mock()
        client.chat.completions.create.return_value = _chat_completion(None)

        with pytest.raises(ProviderError, match="no text"):
            OpenAICompatProvider(client=client, model="m").complete("p", max_tokens=1)

    def test_no_choices_is_provider_error(self):
        client = Mock()
        completion = _chat_completion("x")
        completion.choices = []
        client.chat.completions.create.return_value = completion

        with pytest.raises(ProviderError, match="no text"):
            OpenAICompatProvider(client=client, model="m").complete("p", max_tokens=1)

    def test_missing_usage_counts_as_zero(self):
        client = Mock()
        completion = _chat_completion("x")
        completion.usage = None
        client.chat.completions.create.return_value = completion

        result = OpenAICompatProvider(client=client, model="m").complete("p", max_tokens=1)

        assert (result.input_tokens, result.output_tokens) == (0, 0)


class TestTruncation:
    def test_anthropic_max_tokens_stop_is_truncated(self):
        client = Mock()
        client.messages.create.return_value = _anthropic_message(
            TextBlock(type="text", text='{"a'), stop_reason="max_tokens"
        )

        assert AnthropicProvider(client=client, model="m").complete("p", max_tokens=1).truncated

    def test_anthropic_end_turn_is_not_truncated(self):
        client = Mock()
        client.messages.create.return_value = _anthropic_message(TextBlock(type="text", text="x"))

        assert not AnthropicProvider(client=client, model="m").complete("p", max_tokens=1).truncated

    def test_openai_length_finish_is_truncated(self):
        client = Mock()
        client.chat.completions.create.return_value = _chat_completion(
            '{"a', finish_reason="length"
        )

        assert OpenAICompatProvider(client=client, model="m").complete("p", max_tokens=1).truncated

    def test_openai_stop_finish_is_not_truncated(self):
        client = Mock()
        client.chat.completions.create.return_value = _chat_completion("x")

        assert (
            not OpenAICompatProvider(client=client, model="m").complete("p", max_tokens=1).truncated
        )


@pytest.mark.parametrize("vendor", ["anthropic", "openai"])
class TestAdapterErrorMapping:
    def test_rate_limit_carries_retry_after_seconds(self, vendor):
        error = VENDOR_ERRORS[vendor]["rate_limit"]({"retry-after": "7"})
        provider = _adapter(vendor, _failing_client(vendor, error))

        with pytest.raises(RateLimitError) as exc:
            provider.complete("p", max_tokens=1)

        assert exc.value.retry_after == 7.0

    def test_rate_limit_without_parsable_header_has_no_retry_after(self, vendor):
        error = VENDOR_ERRORS[vendor]["rate_limit"](
            {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}
        )
        provider = _adapter(vendor, _failing_client(vendor, error))

        with pytest.raises(RateLimitError) as exc:
            provider.complete("p", max_tokens=1)

        assert exc.value.retry_after is None

    def test_rate_limit_without_header_has_no_retry_after(self, vendor):
        error = VENDOR_ERRORS[vendor]["rate_limit"]()
        provider = _adapter(vendor, _failing_client(vendor, error))

        with pytest.raises(RateLimitError) as exc:
            provider.complete("p", max_tokens=1)

        assert exc.value.retry_after is None
        assert "slow down" in str(exc.value)

    @pytest.mark.parametrize("kind", ["timeout", "connection", "server"])
    def test_transient_failures_map_to_transient_error(self, vendor, kind):
        error = VENDOR_ERRORS[vendor][kind]()
        provider = _adapter(vendor, _failing_client(vendor, error))

        with pytest.raises(TransientError) as exc:
            provider.complete("p", max_tokens=1)

        assert str(error) in str(exc.value)
        assert exc.value.__cause__ is error

    def test_499_is_not_transient(self, vendor):
        provider = _adapter(vendor, _failing_client(vendor, VENDOR_ERRORS[vendor]["client_499"]()))

        with pytest.raises(ProviderError) as exc:
            provider.complete("p", max_tokens=1)

        assert not isinstance(exc.value, TransientError)

    def test_unknown_model_says_which_and_what_to_do(self, vendor):
        error = VENDOR_ERRORS[vendor]["not_found"]()
        provider = _adapter(vendor, _failing_client(vendor, error))

        with pytest.raises(ModelUnavailableError) as exc:
            provider.complete("p", max_tokens=1)

        message = str(exc.value)
        assert exc.value.model == "m"
        assert message.startswith("model m is not available at this endpoint")
        assert "SEMANTIC_DIFF_MODEL" in message
        assert "model x retired, use y" in message
        assert not isinstance(exc.value, TransientError)
        assert exc.value.__cause__ is error

    def test_client_error_maps_to_provider_error_not_transient(self, vendor):
        provider = _adapter(vendor, _failing_client(vendor, VENDOR_ERRORS[vendor]["client"]()))

        with pytest.raises(ProviderError) as exc:
            provider.complete("p", max_tokens=1)

        assert not isinstance(exc.value, TransientError)
        assert "400" in str(exc.value)


class FlakyProvider:
    """Fake port implementation: raises the scripted errors, then succeeds."""

    model = "flaky-model"

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0
        self.args = []

    def complete(self, prompt, *, max_tokens):
        self.calls += 1
        self.args.append((prompt, max_tokens))
        if self.errors:
            raise self.errors.pop(0)
        return Completion(text="ok", input_tokens=1, output_tokens=1)


class TestRetryingProvider:
    def _retrying(self, inner, **kwargs):
        self.sleeps = []
        defaults = dict(
            max_retries=3,
            base_delay=1.0,
            max_total_wait=100.0,
            sleep=self.sleeps.append,
            jitter=lambda low, high: 0.0,
        )
        return RetryingProvider(inner, **{**defaults, **kwargs})

    def test_passes_through_on_success(self):
        inner = FlakyProvider()

        result = self._retrying(inner).complete("p", max_tokens=5)

        assert result.text == "ok"
        assert inner.args == [("p", 5)]
        assert self.sleeps == []

    def test_does_not_sleep_after_the_last_attempt(self):
        inner = FlakyProvider(TransientError("t0"), TransientError("t1"))

        with pytest.raises(ProviderError):
            self._retrying(inner, max_retries=2).complete("p", max_tokens=5)

        assert self.sleeps == [1.0]

    def test_wait_budget_accumulates_across_retries(self):
        inner = FlakyProvider(*[TransientError(f"t{i}") for i in range(5)])

        with pytest.raises(ProviderError, match="waited 3.0s"):
            self._retrying(inner, max_retries=5, max_total_wait=3.5).complete("p", max_tokens=5)

        assert self.sleeps == [1.0, 2.0]

    def test_delay_exactly_filling_the_budget_is_allowed(self):
        inner = FlakyProvider(RateLimitError("slow", retry_after=30.0))

        self._retrying(inner, max_total_wait=30.0).complete("p", max_tokens=5)

        assert self.sleeps == [30.0]

    def test_jitter_range_is_ten_to_thirty_percent(self):
        seen = []
        inner = FlakyProvider(TransientError("t"))

        self._retrying(inner, jitter=lambda low, high: seen.append((low, high)) or 0.0).complete(
            "p", max_tokens=5
        )

        assert seen == [(0.1, 0.3)]

    def test_single_attempt_means_no_retry(self):
        inner = FlakyProvider(TransientError("t0"))

        with pytest.raises(ProviderError, match="failed after 1 attempts"):
            self._retrying(inner, max_retries=1).complete("p", max_tokens=5)

        assert self.sleeps == []

    def test_at_least_one_attempt_is_required(self):
        with pytest.raises(ValueError, match="max_retries"):
            RetryingProvider(FlakyProvider(), max_retries=0)

    def test_default_base_delay_is_one_second(self):
        sleeps = []
        inner = FlakyProvider(TransientError("t"))

        RetryingProvider(
            inner, max_retries=2, sleep=sleeps.append, jitter=lambda low, high: 0.0
        ).complete("p", max_tokens=5)

        assert sleeps == [1.0]

    def test_wait_budget_default_comes_from_env(self):
        inner = FlakyProvider(TransientError("t"))
        with patch.dict(os.environ, {"SEMANTIC_DIFF_MAX_WAIT": "0.5"}):
            retrying = RetryingProvider(inner, sleep=lambda s: None)

        with pytest.raises(ProviderError, match="waited 0.0s"):
            retrying.complete("p", max_tokens=5)

    def test_retries_transient_with_exponential_backoff(self):
        inner = FlakyProvider(TransientError("t1"), TransientError("t2"))

        result = self._retrying(inner).complete("p", max_tokens=5)

        assert result.text == "ok"
        assert inner.calls == 3
        assert self.sleeps == [1.0, 2.0]

    def test_rate_limit_honours_retry_after(self):
        inner = FlakyProvider(RateLimitError("slow", retry_after=7.0))

        self._retrying(inner).complete("p", max_tokens=5)

        assert self.sleeps == [7.0]

    def test_rate_limit_without_retry_after_backs_off(self):
        inner = FlakyProvider(RateLimitError("slow", retry_after=None))

        self._retrying(inner).complete("p", max_tokens=5)

        assert self.sleeps == [1.0]

    def test_jitter_is_added_to_delay(self):
        inner = FlakyProvider(TransientError("t"))
        retrying = self._retrying(inner, jitter=lambda low, high: high)

        retrying.complete("p", max_tokens=5)

        assert self.sleeps == [pytest.approx(1.3)]

    def test_gives_up_after_max_retries(self):
        inner = FlakyProvider(*[TransientError(f"t{i}") for i in range(5)])

        with pytest.raises(ProviderError, match="failed after 2 attempts.*t1"):
            self._retrying(inner, max_retries=2).complete("p", max_tokens=5)

        assert inner.calls == 2

    def test_stops_when_wait_budget_would_be_exceeded(self):
        inner = FlakyProvider(RateLimitError("slow", retry_after=60.0))

        with pytest.raises(ProviderError, match="waited 0.0s"):
            self._retrying(inner, max_total_wait=30.0).complete("p", max_tokens=5)

        assert self.sleeps == []

    def test_does_not_retry_non_transient_errors(self):
        inner = FlakyProvider(ProviderError("400 bad request"))

        with pytest.raises(ProviderError, match="400 bad request"):
            self._retrying(inner).complete("p", max_tokens=5)

        assert inner.calls == 1

    def test_exposes_inner_model(self):
        assert self._retrying(FlakyProvider()).model == "flaky-model"

    def test_defaults_come_from_env(self):
        inner = FlakyProvider(*[TransientError(f"t{i}") for i in range(5)])
        with patch.dict(os.environ, {"SEMANTIC_DIFF_MAX_RETRIES": "4"}):
            retrying = RetryingProvider(inner, sleep=lambda s: None)

        with pytest.raises(ProviderError):
            retrying.complete("p", max_tokens=5)

        assert inner.calls == 4


class TestBuildProvider:
    def test_default_is_anthropic_wrapped_in_retries(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
            provider = build_provider(load_env=False)

        assert isinstance(provider, RetryingProvider)
        assert isinstance(provider.inner, AnthropicProvider)
        assert provider.model == "claude-sonnet-5-5"

    def test_sdk_clients_get_an_explicit_timeout_for_long_answers(self, monkeypatch):
        # Anthropic's SDK refuses large non-streaming max_tokens unless a timeout is set
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setenv("SEMANTIC_DIFF_API_KEY", "k")
        monkeypatch.setenv("SEMANTIC_DIFF_BASE_URL", "https://llm.example/v1")
        monkeypatch.setenv("SEMANTIC_DIFF_MODEL", "m")

        monkeypatch.setenv("SEMANTIC_DIFF_PROVIDER", "anthropic")
        assert build_provider().inner.client.timeout == 900.0
        monkeypatch.setenv("SEMANTIC_DIFF_PROVIDER", "openai")
        assert build_provider().inner.client.timeout == 900.0

    def test_large_output_limit_passes_the_anthropic_sdk_guard(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        provider = build_provider()
        sent = {}

        def capture(request, **kwargs):
            sent["max_tokens"] = __import__("json").loads(request.content)["max_tokens"]
            raise httpx.ConnectError("offline", request=request)

        provider.inner.client._client.send = capture
        provider.max_retries = 1

        with pytest.raises(ProviderError):
            provider.complete("p", max_tokens=64_000)

        assert sent["max_tokens"] == 64_000

    def test_sdk_clients_do_not_retry_on_their_own(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
            provider = build_provider(load_env=False)

        assert provider.inner.client.max_retries == 0

    def test_openai_compat_uses_base_url_key_and_model(self):
        env = {
            "SEMANTIC_DIFF_PROVIDER": "openai",
            "SEMANTIC_DIFF_API_KEY": "gateway-key",
            "SEMANTIC_DIFF_BASE_URL": "https://llm.example/v2",
            "SEMANTIC_DIFF_MODEL": "claude-sonnet-4.6",
        }
        with patch.dict(os.environ, env, clear=True):
            provider = build_provider(load_env=False)

        inner = provider.inner
        assert isinstance(inner, OpenAICompatProvider)
        assert str(inner.client.base_url).rstrip("/") == "https://llm.example/v2"
        assert inner.client.api_key == "gateway-key"
        assert inner.client.max_retries == 0
        assert provider.model == "claude-sonnet-4.6"

    def test_model_from_env_applies_to_anthropic(self):
        with patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "k", "SEMANTIC_DIFF_MODEL": "env-model"}, clear=True
        ):
            provider = build_provider(load_env=False)

        assert provider.model == "env-model"

    def test_loads_dotenv_by_default(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
            with (
                patch("semantic_diff.user_env.load_dotenv") as load_dotenv,
                patch("semantic_diff.user_env.find_dotenv", return_value="x/.env") as find,
            ):
                build_provider()

        # the .env of the analyzed repository, not one next to the installed package
        find.assert_called_once_with(usecwd=True)
        load_dotenv.assert_called_once_with("x/.env")

    def test_openai_provider_without_sdk_explains_the_extra(self):
        env = {
            "SEMANTIC_DIFF_PROVIDER": "openai",
            "SEMANTIC_DIFF_API_KEY": "k",
            "SEMANTIC_DIFF_BASE_URL": "https://llm.example/v2",
            "SEMANTIC_DIFF_MODEL": "m",
        }
        with patch.dict(os.environ, env, clear=True), patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ValueError, match=r"semantic-diff\[openai\]"):
                build_provider(load_env=False)

    def test_package_rejects_unknown_attributes(self):
        import semantic_diff.providers as providers

        with pytest.raises(AttributeError, match="Nope"):
            providers.Nope  # noqa: B018

    def test_explicit_model_beats_env(self):
        with patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "k", "SEMANTIC_DIFF_MODEL": "env-model"}, clear=True
        ):
            provider = build_provider(model="cli-model", load_env=False)

        assert provider.model == "cli-model"

    def test_openai_compat_requires_base_url(self):
        env = {"SEMANTIC_DIFF_PROVIDER": "openai", "SEMANTIC_DIFF_API_KEY": "k"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="SEMANTIC_DIFF_BASE_URL"):
                build_provider(load_env=False)

    def test_openai_compat_requires_model(self):
        env = {
            "SEMANTIC_DIFF_PROVIDER": "openai",
            "SEMANTIC_DIFF_API_KEY": "k",
            "SEMANTIC_DIFF_BASE_URL": "https://llm.example/v2",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="SEMANTIC_DIFF_MODEL"):
                build_provider(load_env=False)

    def test_missing_key_names_the_variable(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                build_provider(load_env=False)

    def test_unknown_provider_lists_known_ones(self):
        with patch.dict(os.environ, {"SEMANTIC_DIFF_PROVIDER": "bard"}, clear=True):
            with pytest.raises(ValueError, match="bard.*anthropic, openai"):
                build_provider(load_env=False)


class TestPackageWithoutOpenAIExtra:
    """The openai extra is optional: the package must import without it"""

    @staticmethod
    def _run_without_openai(code):
        import subprocess
        import sys

        # sys.modules["openai"] = None makes any `import openai` raise ImportError
        script = "import sys; sys.modules['openai'] = None\n" + code
        return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    def test_star_import_works(self):
        result = self._run_without_openai("from semantic_diff.providers import *")

        assert result.returncode == 0, result.stderr

    def test_star_import_does_not_export_the_optional_adapter(self):
        from semantic_diff import providers

        assert "OpenAICompatProvider" not in providers.__all__

    def test_optional_adapter_is_still_importable_by_name(self):
        from semantic_diff.providers import OpenAICompatProvider as Lazy
        from semantic_diff.providers.openai_compat import OpenAICompatProvider as Direct

        assert Lazy is Direct
