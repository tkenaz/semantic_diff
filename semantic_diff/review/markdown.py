"""
The review report as Markdown. Everything the model wrote is escaped: it may
quote repository content, and repository content is untrusted.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Callable, List

from semantic_diff.formatters.markdown_formatter import MarkdownFormatter, escape_md, escape_path
from semantic_diff.models import RiskLevel
from semantic_diff.review.report import Finding, ReviewReport

SEVERITY_ORDER = [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW]

LIMIT_WORDS = {"turns": "turn limit", "tokens": "token budget", "context": "context size limit"}


class ReviewMarkdownFormatter:
    def __init__(self, now: Callable[[], datetime] = datetime.now):
        self._now = now

    def format(self, report: ReviewReport) -> str:
        cs = report.change_set
        verdict = report.verdict.replace("_", " ") if report.verdict else "none"
        lines = [
            f"# Review: {cs.ref}",
            "",
            f"**{escape_md(cs.title)}**",
            "",
            f"**Verdict:** {verdict} · {report.review_model} · {report.review_timestamp}",
            "",
        ]
        lines += _overruled(report)
        lines += _warning(report)
        lines += ["## Summary", "", escape_md(report.summary), ""]
        lines += [f"## Findings ({len(report.findings)})", ""]
        if not report.findings:
            lines += ["No findings.", ""]
        ranked = sorted(report.findings, key=lambda f: SEVERITY_ORDER.index(f.severity))
        for number, finding in enumerate(ranked, 1):
            lines += _finding(number, finding)
        lines += ["## How the review went", ""]
        lines += _how_it_went(report)
        return "\n".join(lines)

    def save(self, report: ReviewReport, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self._now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"review_{report.change_set.head_sha[:8]}_{timestamp}.md"
        path.write_text(self.format(report), encoding="utf-8")
        return path


def _overruled(report: ReviewReport) -> List[str]:
    if not report.verdict_note:
        return []
    proposed = (report.submitted_verdict or "none").replace("_", " ")
    verdict = (report.verdict or "none").replace("_", " ")
    return [
        f"> The reviewer proposed **{proposed}**; the verdict is **{verdict}**: "
        f"{report.verdict_note}.",
        "",
    ]


def _warning(report: ReviewReport) -> List[str]:
    limit = LIMIT_WORDS.get(report.stats.limit_hit or "")
    if not report.stats.submitted:
        stopped = f" (stopped by the {limit})" if limit else ""
        return [
            f"> ⚠ **Incomplete review:** the model did not submit a review{stopped}.",
            "",
        ]
    if limit:
        return [f"> ⚠ Wrapped up early by the {limit}: parts of the change may be unchecked.", ""]
    return []


def _finding(number: int, finding: Finding) -> List[str]:
    icon = MarkdownFormatter.RISK_ICONS[finding.severity]
    where = _code(f"{finding.file}:{finding.line}")
    lines = [
        f"### {number}. {icon} {finding.severity.value.upper()} · {where} · "
        f"{escape_md(finding.title)}",
        "",
        escape_md(finding.explanation),
        "",
    ]
    if finding.suggestion:
        lines += [f"**Suggestion:** {escape_md(finding.suggestion)}", ""]
    for note in _notes(finding):
        lines += [f"> {note}", ""]
    return lines


def _notes(finding: Finding) -> List[str]:
    path = escape_path(finding.file)
    notes = {
        "base": ["Cites code as it was before the change (removed or moved)."],
        "no_such_line": [f"⚠ {path} has no line {finding.line}: check this finding by hand."],
        "no_such_file": [f"⚠ {path} does not exist: check this finding by hand."],
    }.get(finding.citation, [])
    if not finding.seen:
        notes.append("⚠ The reviewer never opened this file: treat this finding as a guess.")
    return notes


def _how_it_went(report: ReviewReport) -> List[str]:
    stats = report.stats
    files = ", ".join(escape_path(p) for p in stats.files_read) or "none beyond the diff"
    cov = report.diff_coverage
    lines = [
        f"- {stats.turns} turns, {stats.tool_calls} tool calls",
        f"- Tokens: {stats.input_tokens:,} in ({stats.cache_read_tokens:,} read from cache, "
        f"{stats.cache_write_tokens:,} written to cache), {stats.output_tokens:,} out",
        f"- Files read: {files}",
        f"- Diff coverage: {cov.percent}% of changed lines shown up front "
        f"(budget {cov.budget_tokens:,} tokens)",
    ]
    for label, paths in (
        ("Trimmed to whole hunks", cov.trimmed),
        ("Not shown up front", cov.omitted),
        ("Skipped (lock/generated/binary)", cov.noise),
    ):
        if paths:
            lines.append(f"  - {label}: {', '.join(escape_path(p) for p in paths)}")
    return lines + [""]


def _code(location: str) -> str:
    # CommonMark: a span opened by N backticks closes only at a run of exactly N.
    # A location ends with its line number, so only a leading backtick needs padding.
    fence = "`" * (max((len(run) for run in re.findall(r"`+", location)), default=0) + 1)
    padded = f" {location} " if location.startswith("`") else location
    return f"{fence}{padded}{fence}"
