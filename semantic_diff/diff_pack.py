"""
Fit a change set's diffs into a token budget.

Pure: no git, no LLM. Files are shown riskiest tier first; a file that does
not fit whole is trimmed at hunk boundaries (never mid-line); lock files,
generated output and binaries are listed but never shown. The returned
coverage says exactly what the model did not see.
"""

import math
import re
from dataclasses import dataclass
from enum import IntEnum
from pathlib import PurePosixPath
from typing import List

from semantic_diff.models import DiffCoverage, FileChange

CHARS_PER_TOKEN = 3.5
DEFAULT_BUDGET_TOKENS = 60_000


class Tier(IntEnum):
    """Showing order under a budget - lower is shown first"""

    CODE = 0
    MIGRATION = 1
    INFRA = 2
    TEST = 3
    DOCS = 4
    NOISE = 5


NOISE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
}
NOISE_DIRS = {"dist", "build", "node_modules", "__snapshots__"}
# Matched from the right by PurePosixPath.match
NOISE_PATTERNS = (
    "*.snap",
    "*.min.js",
    "*.min.css",
    "*.map",
    "meta/_journal.json",
    "meta/*_snapshot.json",
)

TEST_DIRS = {"test", "tests", "__tests__", "e2e", "spec"}
TEST_NAME = re.compile(r"(^test_.*|.*_test\.\w+|.*\.(test|spec)\.\w+)$")
MIGRATION_DIRS = {"migrations", "migration"}
DOCS_SUFFIXES = {".md", ".rst", ".adoc", ".txt"}
INFRA_DIRS = {"ci", "helm", "charts", "infra", "terraform", ".github", "k8s"}
INFRA_SUFFIXES = {".tf", ".hcl", ".yml", ".yaml"}

HUNK_HEADER = re.compile(r"^@@ ", re.MULTILINE)


@dataclass(frozen=True)
class ShownDiff:
    file: FileChange
    text: str
    hunks_shown: int
    hunks_total: int

    @property
    def trimmed(self) -> bool:
        return self.hunks_shown < self.hunks_total


@dataclass(frozen=True)
class DiffPack:
    shown: List[ShownDiff]
    coverage: DiffCoverage


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def classify(path: str) -> Tier:
    # A rename is judged by where the file lives now
    p = PurePosixPath(path.split(" -> ")[-1])
    dirs = set(p.parts[:-1])

    if p.name in NOISE_NAMES or dirs & NOISE_DIRS or any(p.match(g) for g in NOISE_PATTERNS):
        return Tier.NOISE
    if dirs & TEST_DIRS or TEST_NAME.match(p.name):
        return Tier.TEST
    if dirs & MIGRATION_DIRS or p.suffix == ".sql":
        return Tier.MIGRATION
    if p.suffix in DOCS_SUFFIXES or "docs" in dirs:
        return Tier.DOCS
    if dirs & INFRA_DIRS or p.name.startswith("Dockerfile") or p.suffix in INFRA_SUFFIXES:
        return Tier.INFRA
    return Tier.CODE


def _is_binary(change: FileChange) -> bool:
    return change.diff_content.startswith("Binary files ")


def _hunks(diff: str) -> List[str]:
    # Text before the first @@ (or a diff without any) is a piece of its own
    bounds = sorted({0, *(m.start() for m in HUNK_HEADER.finditer(diff))}) + [len(diff)]
    return [diff[a:b].rstrip("\n") for a, b in zip(bounds, bounds[1:])]


def _changed_lines(text: str) -> int:
    return sum(1 for line in text.split("\n") if line[:1] in ("+", "-"))


def pack(files: List[FileChange], budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> DiffPack:
    if budget_tokens < 1:
        raise ValueError(f"Diff budget must be at least 1 token, got {budget_tokens}")

    noise = [f for f in files if classify(f.path) is Tier.NOISE or _is_binary(f)]
    candidates = sorted(
        (f for f in files if f not in noise and f.diff_content),
        key=lambda f: classify(f.path),
    )

    shown: List[ShownDiff] = []
    omitted: List[str] = []
    used = 0
    for change in candidates:
        hunks = _hunks(change.diff_content)
        taken: List[str] = []
        for hunk in hunks:
            cost = estimate_tokens("\n".join(taken + [hunk]))
            if used + cost > budget_tokens:
                break
            taken.append(hunk)
        if not taken:
            omitted.append(change.path)
            continue
        text = "\n".join(taken)
        used += estimate_tokens(text)
        shown.append(ShownDiff(change, text, len(taken), len(hunks)))

    coverage = DiffCoverage(
        budget_tokens=budget_tokens,
        shown_lines=sum(_changed_lines(s.text) for s in shown),
        total_lines=sum(_changed_lines(f.diff_content) for f in candidates),
        trimmed=[s.file.path for s in shown if s.trimmed],
        omitted=omitted,
        noise=[f.path for f in noise],
    )
    return DiffPack(shown=shown, coverage=coverage)
