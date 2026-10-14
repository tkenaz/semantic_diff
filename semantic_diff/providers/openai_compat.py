"""
Adapter: OpenAI Chat Completions protocol, for any compatible gateway
(e.g. T-Systems AIFS, vLLM, LiteLLM, OpenAI itself).
"""

import json
from typing import Any, Dict, List, Sequence

import openai

from semantic_diff.providers.base import (
    AssistantMessage,
    Completion,
    Message,
    ProviderError,
    RateLimitError,
    StopReason,
    ToolCall,
    ToolResult,
    ToolSpec,
    TransientError,
    Turn,
    UserMessage,
    parse_retry_after,
)

# Anthropic-style prompt caching; AIFS passes it through on content blocks
CACHE = {"type": "ephemeral"}

STOP_REASONS = {"tool_calls": StopReason.TOOL_USE, "length": StopReason.MAX_TOKENS}


class OpenAICompatProvider:
    def __init__(self, client: openai.OpenAI, model: str):
        self.client = client
        self.model = model

    def complete(self, prompt: str, *, max_tokens: int) -> Completion:
        response = self._create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise ProviderError("Model response contains no text")
        usage = response.usage
        return Completion(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            truncated=response.choices[0].finish_reason == "length",
        )

    def converse(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        max_tokens: int,
    ) -> Turn:
        request: Dict[str, Any] = {"model": self.model, "max_tokens": max_tokens}
        if tools:
            request["tools"] = [_tool_spec(t) for t in tools]
        request["messages"] = _with_cache_breakpoints(
            [{"role": "system", "content": [_text(system)]}, *map(_message, messages)]
        )

        response = self._create(**request)

        if not response.choices:
            raise ProviderError("Model response contains no choices")
        choice = response.choices[0]
        calls = tuple(_tool_call(c) for c in choice.message.tool_calls or ())
        usage = response.usage
        return Turn(
            text=choice.message.content or "",
            tool_calls=calls,
            # Some gateways say "stop" on a turn that carries tool calls
            stop_reason=(
                StopReason.TOOL_USE
                if calls
                else STOP_REASONS.get(choice.finish_reason, StopReason.END)
            ),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
        )

    def _create(self, **request):
        try:
            return self.client.chat.completions.create(**request)
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


def _text(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def _tool_spec(tool: ToolSpec) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _message(message: Message) -> Dict[str, Any]:
    if isinstance(message, UserMessage):
        return {"role": "user", "content": [_text(message.text)]}
    if isinstance(message, ToolResult):
        content = f"ERROR: {message.content}" if message.is_error else message.content
        return {"role": "tool", "tool_call_id": message.call_id, "content": [_text(content)]}
    return _assistant(message)


def _assistant(message: AssistantMessage) -> Dict[str, Any]:
    if not message.tool_calls:
        return {"role": "assistant", "content": message.text}
    return {
        "role": "assistant",
        "content": message.text or None,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.name,
                    "arguments": (
                        json.dumps(c.arguments) if c.arguments is not None else c.raw_arguments
                    ),
                },
            }
            for c in message.tool_calls
        ],
    }


def _with_cache_breakpoints(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # The system prompt (tools sit before it) and the newest message: each turn
    # then re-reads everything up to the previous turn from cache.
    for index in sorted({0, len(messages) - 1}):
        content = messages[index]["content"]
        if isinstance(content, list):
            marked = {**content[-1], "cache_control": CACHE}
            messages[index] = {**messages[index], "content": [*content[:-1], marked]}
    return messages


def _tool_call(call) -> ToolCall:
    raw = call.function.arguments or ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    return ToolCall(
        id=call.id,
        name=call.function.name,
        arguments=parsed if isinstance(parsed, dict) else None,
        raw_arguments=raw,
    )
