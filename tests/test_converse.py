"""
Tests for the tool-calling side of the LLM port: converse() with tools, as
used by the review agent. Adapters are tested against real SDK types, only the
network client is faked.
"""

from unittest.mock import Mock

import httpx
import openai
import pytest
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

from semantic_diff.providers import (
    AssistantMessage,
    OpenAICompatProvider,
    ProviderError,
    RateLimitError,
    RetryingProvider,
    StopReason,
    ToolCall,
    ToolResult,
    ToolSpec,
    TransientError,
    Turn,
    UserMessage,
)

REQUEST = httpx.Request("POST", "https://llm.example/v1")
CACHE = {"type": "ephemeral"}

READ_FILE = ToolSpec(
    name="read_file",
    description="Read a file",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)


def _tool_call(call_id: str, name: str, arguments: str) -> ChatCompletionMessageToolCall:
    return ChatCompletionMessageToolCall(
        id=call_id, type="function", function=Function(name=name, arguments=arguments)
    )


def _completion(content=None, tool_calls=None, finish_reason="stop", usage=None) -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-1",
        object="chat.completion",
        created=0,
        model="claude-opus-4.6",
        choices=[
            Choice(
                index=0,
                finish_reason=finish_reason,
                message=ChatCompletionMessage(
                    role="assistant", content=content, tool_calls=tool_calls
                ),
            )
        ],
        usage=usage,
    )


def _usage(prompt=100, completion=20, **extra) -> CompletionUsage:
    # AIFS reports Anthropic cache counters as extra usage fields
    return CompletionUsage.model_validate(
        {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            **extra,
        }
    )


def _provider(response) -> tuple:
    client = Mock()
    client.chat.completions.create.return_value = response
    return OpenAICompatProvider(client=client, model="claude-opus-4.6"), client


def _sent(client) -> dict:
    return client.chat.completions.create.call_args.kwargs


class TestOpenAIConverseRequest:
    def test_sends_system_tools_and_conversation_in_openai_shape(self):
        provider, client = _provider(_completion("done"))
        call = ToolCall(id="t1", name="read_file", arguments={"path": "a.py"}, raw_arguments="")

        provider.converse(
            "You review code.",
            [
                UserMessage("Review this."),
                AssistantMessage("Reading.", (call,)),
                ToolResult("t1", "print(1)"),
            ],
            [READ_FILE],
            max_tokens=500,
        )

        assert _sent(client) == {
            "model": "claude-opus-4.6",
            "max_tokens": 500,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": READ_FILE.parameters,
                    },
                }
            ],
            "messages": [
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": "You review code.", "cache_control": CACHE}
                    ],
                },
                {"role": "user", "content": [{"type": "text", "text": "Review this."}]},
                {
                    "role": "assistant",
                    "content": "Reading.",
                    "tool_calls": [
                        {
                            "id": "t1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "t1",
                    "content": [{"type": "text", "text": "print(1)", "cache_control": CACHE}],
                },
            ],
        }

    def test_cache_marks_only_the_system_prompt_and_the_last_message(self):
        provider, client = _provider(_completion("done"))

        provider.converse(
            "sys",
            [UserMessage("one"), AssistantMessage("two"), UserMessage("three")],
            [],
            max_tokens=1,
        )

        marked = [
            m["role"]
            for m in _sent(client)["messages"]
            if isinstance(m["content"], list) and "cache_control" in m["content"][-1]
        ]
        assert marked == ["system", "user"]
        assert _sent(client)["messages"][-1]["content"][0]["text"] == "three"

    def test_assistant_without_tool_calls_sends_no_tool_calls_key(self):
        provider, client = _provider(_completion("done"))

        provider.converse("sys", [AssistantMessage("hm"), UserMessage("go")], [], max_tokens=1)

        assert _sent(client)["messages"][1] == {"role": "assistant", "content": "hm"}

    def test_assistant_with_only_tool_calls_sends_null_content(self):
        provider, client = _provider(_completion("done"))
        call = ToolCall(id="t1", name="read_file", arguments={}, raw_arguments="{}")

        provider.converse(
            "sys", [AssistantMessage("", (call,)), ToolResult("t1", "x")], [], max_tokens=1
        )

        assert _sent(client)["messages"][1]["content"] is None

    def test_tool_call_with_unparsable_arguments_is_echoed_back_raw(self):
        provider, client = _provider(_completion("done"))
        call = ToolCall(id="t1", name="read_file", arguments=None, raw_arguments="{oops")

        provider.converse(
            "sys", [AssistantMessage("", (call,)), ToolResult("t1", "bad args")], [], max_tokens=1
        )

        assert _sent(client)["messages"][1]["tool_calls"][0]["function"]["arguments"] == "{oops"

    def test_error_tool_result_is_marked_for_the_model(self):
        provider, client = _provider(_completion("done"))

        provider.converse("sys", [ToolResult("t1", "no such file")], [], max_tokens=1)

        assert _sent(client)["messages"][-1]["content"][0]["text"] == "no such file"
        provider.converse(
            "sys", [ToolResult("t1", "no such file", is_error=True)], [], max_tokens=1
        )

        assert _sent(client)["messages"][-1]["content"][0]["text"] == "ERROR: no such file"

    def test_no_tools_sends_no_tools_key(self):
        provider, client = _provider(_completion("done"))

        provider.converse("sys", [UserMessage("hi")], [], max_tokens=1)

        assert "tools" not in _sent(client)


class TestOpenAIConverseResponse:
    def test_tool_calls_become_a_tool_use_turn(self):
        provider, _ = _provider(
            _completion(
                "Let me look.",
                [
                    _tool_call("toolu_1", "read_file", '{"path": "a.py"}'),
                    _tool_call("toolu_2", "grep", '{"pattern": "x"}'),
                ],
                finish_reason="tool_calls",
                usage=_usage(100, 20, cache_read_input_tokens=80, cache_creation_input_tokens=15),
            )
        )

        turn = provider.converse("sys", [UserMessage("hi")], [READ_FILE], max_tokens=1)

        assert turn == Turn(
            text="Let me look.",
            tool_calls=(
                ToolCall("toolu_1", "read_file", {"path": "a.py"}, '{"path": "a.py"}'),
                ToolCall("toolu_2", "grep", {"pattern": "x"}, '{"pattern": "x"}'),
            ),
            stop_reason=StopReason.TOOL_USE,
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=80,
            cache_write_tokens=15,
        )

    @pytest.mark.parametrize(
        "finish_reason, stop_reason",
        [
            ("stop", StopReason.END),
            ("length", StopReason.MAX_TOKENS),
            ("tool_calls", StopReason.TOOL_USE),
            ("content_filter", StopReason.END),
        ],
    )
    def test_finish_reason_mapping(self, finish_reason, stop_reason):
        provider, _ = _provider(_completion("x", finish_reason=finish_reason))

        turn = provider.converse("sys", [UserMessage("hi")], [], max_tokens=1)

        assert turn.stop_reason is stop_reason

    def test_tool_calls_win_over_an_unexpected_finish_reason(self):
        # Some gateways report "stop" even when the turn carries tool calls
        provider, _ = _provider(_completion(None, [_tool_call("t", "grep", "{}")], "stop"))

        turn = provider.converse("sys", [UserMessage("hi")], [], max_tokens=1)

        assert turn.stop_reason is StopReason.TOOL_USE

    @pytest.mark.parametrize("raw", ["{not json", "[1, 2]", '"text"', ""])
    def test_arguments_that_are_not_a_json_object_are_kept_raw(self, raw):
        provider, _ = _provider(_completion(None, [_tool_call("t", "grep", raw)], "tool_calls"))

        [call] = provider.converse("sys", [UserMessage("hi")], [], max_tokens=1).tool_calls

        assert (call.arguments, call.raw_arguments) == (None, raw)

    def test_missing_text_is_empty_string(self):
        provider, _ = _provider(_completion(None, [_tool_call("t", "grep", "{}")], "tool_calls"))

        assert provider.converse("sys", [UserMessage("hi")], [], max_tokens=1).text == ""

    def test_missing_usage_and_cache_counters_count_as_zero(self):
        provider, _ = _provider(_completion("x"))
        turn = provider.converse("sys", [UserMessage("hi")], [], max_tokens=1)
        assert (turn.input_tokens, turn.output_tokens) == (0, 0)
        assert (turn.cache_read_tokens, turn.cache_write_tokens) == (0, 0)

        provider, _ = _provider(_completion("x", usage=_usage(9, 3)))
        turn = provider.converse("sys", [UserMessage("hi")], [], max_tokens=1)
        assert (turn.input_tokens, turn.output_tokens) == (9, 3)
        assert (turn.cache_read_tokens, turn.cache_write_tokens) == (0, 0)

    def test_no_choices_is_provider_error(self):
        completion = _completion("x")
        completion.choices = []
        provider, _ = _provider(completion)

        with pytest.raises(ProviderError, match="no choices"):
            provider.converse("sys", [UserMessage("hi")], [], max_tokens=1)

    def test_turn_converts_to_the_assistant_message_that_continues_the_conversation(self):
        call = ToolCall("t1", "grep", {"pattern": "x"}, '{"pattern": "x"}')
        turn = Turn("Looking.", (call,), StopReason.TOOL_USE, 1, 1)

        assert turn.as_message() == AssistantMessage("Looking.", (call,))


class TestOpenAIConverseErrors:
    def test_rate_limit_maps_like_complete(self):
        client = Mock()
        client.chat.completions.create.side_effect = openai.RateLimitError(
            "slow",
            response=httpx.Response(429, headers={"retry-after": "4"}, request=REQUEST),
            body={},
        )

        with pytest.raises(RateLimitError) as exc:
            OpenAICompatProvider(client=client, model="m").converse(
                "sys", [UserMessage("hi")], [], max_tokens=1
            )

        assert exc.value.retry_after == 4.0

    def test_server_error_is_transient_client_error_is_not(self):
        client = Mock()
        provider = OpenAICompatProvider(client=client, model="m")

        client.chat.completions.create.side_effect = openai.InternalServerError(
            "boom", response=httpx.Response(502, request=REQUEST), body={}
        )
        with pytest.raises(TransientError):
            provider.converse("sys", [UserMessage("hi")], [], max_tokens=1)

        client.chat.completions.create.side_effect = openai.BadRequestError(
            "bad", response=httpx.Response(400, request=REQUEST), body={}
        )
        with pytest.raises(ProviderError) as exc:
            provider.converse("sys", [UserMessage("hi")], [], max_tokens=1)
        assert not isinstance(exc.value, TransientError)


class ScriptedConverser:
    model = "scripted"

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = []

    def converse(self, system, messages, tools, *, max_tokens):
        self.calls.append((system, list(messages), list(tools), max_tokens))
        if self.errors:
            raise self.errors.pop(0)
        return Turn("ok", (), StopReason.END, 1, 1)


class TestRetryingConverse:
    def test_retries_transient_failures_with_the_same_policy_as_complete(self):
        sleeps = []
        inner = ScriptedConverser(TransientError("drop"), RateLimitError("429", retry_after=7.0))
        retrying = RetryingProvider(
            inner,
            max_retries=3,
            base_delay=1.0,
            max_total_wait=100.0,
            sleep=sleeps.append,
            jitter=lambda low, high: 0.0,
        )

        turn = retrying.converse("sys", [UserMessage("hi")], [READ_FILE], max_tokens=9)

        assert turn.text == "ok"
        assert sleeps == [1.0, 7.0]
        assert inner.calls[-1] == ("sys", [UserMessage("hi")], [READ_FILE], 9)

    def test_gives_up_with_provider_error(self):
        inner = ScriptedConverser(*[TransientError("drop")] * 3)
        retrying = RetryingProvider(
            inner, max_retries=2, max_total_wait=100.0, sleep=lambda s: None
        )

        with pytest.raises(ProviderError, match="after 2 attempts"):
            retrying.converse("sys", [UserMessage("hi")], [], max_tokens=1)

    def test_logs_which_retry_is_coming_and_when_the_wait_budget_stops_it(self, caplog):
        inner = ScriptedConverser(TransientError("drop"), TransientError("drop"))
        retrying = RetryingProvider(
            inner,
            max_retries=3,
            base_delay=1.0,
            max_total_wait=2.0,
            sleep=lambda s: None,
            jitter=lambda low, high: 0.0,
        )

        with caplog.at_level("WARNING"), pytest.raises(ProviderError):
            retrying.converse("sys", [UserMessage("hi")], [], max_tokens=1)

        assert [r.getMessage() for r in caplog.records] == [
            "drop; retry 1/3 in 1.0s",
            "Retry would exceed max_total_wait (2.0s)",
        ]
