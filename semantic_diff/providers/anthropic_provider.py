"""
Adapter: Anthropic Messages API.
"""

import json
from typing import Any, Dict, List, Sequence

import anthropic

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

# Anthropic prompt caching: a breakpoint on the system prompt and on the
# newest message, so each turn re-reads the conversation so far from cache.
CACHE = {"type": "ephemeral"}

STOP_REASONS = {"tool_use": StopReason.TOOL_USE, "max_tokens": StopReason.MAX_TOKENS}


class AnthropicProvider:
    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client = client
        self.model = model

    def complete(self, prompt: str, *, max_tokens: int) -> Completion:
        response = self._create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        # content[0] is not guaranteed to be text (thinking blocks come first)
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise ProviderError("Model response contains no text block")
        return Completion(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            truncated=response.stop_reason == "max_tokens",
        )

    def converse(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        max_tokens: int,
    ) -> Turn:
        request: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": CACHE}],
            "messages": _mark_newest(_messages(messages)),
        }
        if tools:
            request["tools"] = [_tool_spec(t) for t in tools]

        response = self._create(**request)

        text = "".join(block.text for block in response.content if block.type == "text")
        calls = tuple(_tool_call(block) for block in response.content if block.type == "tool_use")
        usage = response.usage
        return Turn(
            text=text,
            tool_calls=calls,
            stop_reason=(
                StopReason.TOOL_USE
                if calls
                else STOP_REASONS.get(response.stop_reason, StopReason.END)
            ),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
        )

    def _create(self, **request):
        try:
            return self.client.messages.create(**request)
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


def _text(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def _tool_spec(tool: ToolSpec) -> Dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": dict(tool.parameters),
    }


def _messages(messages: Sequence[Message]) -> List[Dict[str, Any]]:
    """Port messages to API shape; consecutive tool results share one user message."""
    out: List[Dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ToolResult):
            block = {
                "type": "tool_result",
                "tool_use_id": message.call_id,
                "content": message.content,
            }
            if message.is_error:
                block["is_error"] = True
            # All results of one assistant turn must arrive in one user message
            if (
                out
                and out[-1]["role"] == "user"
                and out[-1]["content"][-1]["type"] == "tool_result"
            ):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif isinstance(message, UserMessage):
            out.append({"role": "user", "content": [_text(message.text)]})
        else:
            out.append(_assistant(message))
    return out


def _assistant(message: AssistantMessage) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = []
    if message.text:
        content.append(_text(message.text))
    for call in message.tool_calls:
        content.append(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                # tool_use input must be an object; these calls came from this
                # same API, so arguments is None only for a malformed replay
                "input": call.arguments if call.arguments is not None else {},
            }
        )
    return {"role": "assistant", "content": content}


def _mark_newest(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if messages:
        content = messages[-1]["content"]
        content[-1] = {**content[-1], "cache_control": CACHE}
    return messages


def _tool_call(block) -> ToolCall:
    arguments = block.input if isinstance(block.input, dict) else None
    return ToolCall(
        id=block.id,
        name=block.name,
        arguments=arguments,
        raw_arguments=json.dumps(block.input) if block.input is not None else "",
    )
