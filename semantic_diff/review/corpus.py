"""
A rule corpus the reviewer cites: a local directory with `INDEX.md` (the
signal -> tags table) and `rules/*.md` (atomic rule cards, one `### [ID] ...`
heading per card). The layout follows the 37lab compliance-review skill; any
checkout with that shape plugs in.

The corpus has two jobs here:
- give the model the cards (INDEX.md inlined up front, rule files on demand
  through the `read_rules` tool), and
- give the agent the set of real card ids, so a cited `rule_id` that does not
  exist in the corpus is caught in code, never trusted.
"""

import re
from pathlib import Path
from typing import FrozenSet, List, Tuple

from semantic_diff.providers import ToolCall, ToolResult, ToolSpec

CARD_ID = re.compile(r"^###\s*\[([^\]\s]+)\]", re.MULTILINE)

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
        if not self.rule_files:
            raise ValueError(f"rules corpus has no rules/*.md files: {self.root}")

    @property
    def index_text(self) -> str:
        return (self.root / "INDEX.md").read_text(encoding="utf-8")

    @property
    def rule_files(self) -> List[str]:
        return sorted(f"rules/{path.name}" for path in (self.root / "rules").glob("*.md"))

    @property
    def rule_ids(self) -> FrozenSet[str]:
        ids = []
        for name in self.rule_files:
            ids += CARD_ID.findall((self.root / name).read_text(encoding="utf-8"))
        return frozenset(ids)

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
