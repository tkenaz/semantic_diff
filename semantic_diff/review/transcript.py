"""
The whole conversation of a review, one JSON object per line: what the model
was told, every tool call it made and every result it got. For diagnosing
where a review spent its turns - the report only says how many it spent.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Sequence

from semantic_diff.providers import AssistantMessage, Message, ToolResult, UserMessage

# Receives the system prompt and the full conversation when a review ends
TranscriptSink = Callable[[str, Sequence[Message]], None]

ROLES = {UserMessage: "user", AssistantMessage: "assistant", ToolResult: "tool"}


def transcript_lines(system: str, messages: Sequence[Message]) -> list:
    lines = [{"role": "system", "text": system}]
    lines += [{"role": ROLES[type(m)], **asdict(m)} for m in messages]
    return lines


def file_sink(path: Path) -> TranscriptSink:
    def write(system: str, messages: Sequence[Message]) -> None:
        rows = (json.dumps(line, ensure_ascii=False) for line in transcript_lines(system, messages))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    return write
