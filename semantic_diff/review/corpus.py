"""
A rule corpus the reviewer cites: a local directory with `INDEX.md` (the
signal -> tags table) and `rules/*.md` (atomic rule cards, one `### [ID] ...`
heading per card). The layout follows the 37lab compliance-review skill; any
checkout with that shape plugs in.

The corpus has two jobs here:
- give the model the cards (INDEX.md inlined up front, rule files on demand
  through the `read_rules` tool), and
- give the agent the set of real card ids, so a cited `rule_id` that does not
  exist in the corpus is caught in code, never trusted, and each card's source
  line, so the source a report prints is the card's, not the model's copy.

The directory is read once: the files a review may load do not change under it.
"""

import re
from pathlib import Path
from typing import Dict, FrozenSet, List, Tuple

from semantic_diff.providers import ToolCall, ToolResult, ToolSpec

CARD_ID = re.compile(r"^###\s*\[([^\]\s]+)\]", re.MULTILINE)
CARD_SOURCE = re.compile(r"^source:[ \t]*(.+?)\s*$", re.MULTILINE)

READ_RULES = ToolSpec(
    "read_rules",
    "Read a file of the rule corpus: 'INDEX.md' or a rule file it names "
    "(e.g. 'rules/authz.md'). Load only the rule files whose tags the diff earned.",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Corpus-relative path: INDEX.md or rules/<name>.md",
            }
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)


class RulesCorpus:
    def __init__(self, root: Path):
        self.root = Path(root)
        index = self.root / "INDEX.md"
        if not index.is_file():
            raise ValueError(f"rules corpus has no INDEX.md: {self.root}")
        self.index_text = index.read_text(encoding="utf-8")
        self.rule_files: List[str] = sorted(
            f"rules/{path.name}" for path in (self.root / "rules").glob("*.md")
        )
        if not self.rule_files:
            raise ValueError(f"rules corpus has no rules/*.md files: {self.root}")
        self.sources: Dict[str, str] = {}
        for name in self.rule_files:
            self.sources.update(_card_sources((self.root / name).read_text(encoding="utf-8")))
        self.rule_ids: FrozenSet[str] = frozenset(self.sources)

    @property
    def specs(self) -> Tuple[ToolSpec, ...]:
        return (READ_RULES,)

    @property
    def tool_names(self) -> FrozenSet[str]:
        return frozenset(spec.name for spec in self.specs)

    def run(self, call: ToolCall) -> ToolResult:
        if call.arguments is None or not isinstance(call.arguments.get("path"), str):
            return ToolResult(
                call.id, f"path must be a string, got: {call.raw_arguments}", is_error=True
            )
        clean = call.arguments["path"].strip().removeprefix("./")
        # Only the files the corpus is made of; nothing else on this machine
        if clean != "INDEX.md" and clean not in self.rule_files:
            available = ", ".join(["INDEX.md", *self.rule_files])
            return ToolResult(
                call.id, f"no such corpus file: {clean}; available: {available}", is_error=True
            )
        return ToolResult(call.id, (self.root / clean).read_text(encoding="utf-8"))


def _card_sources(text: str) -> Dict[str, str]:
    """Card id -> its source line ('' for a card without one)."""
    headings = list(CARD_ID.finditer(text))
    sources = {}
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        source = CARD_SOURCE.search(text, heading.end(), end)
        sources[heading.group(1)] = source.group(1) if source else ""
    return sources
