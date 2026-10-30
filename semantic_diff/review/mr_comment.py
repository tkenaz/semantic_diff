"""
The review as one merge request comment: the verdict, the cited findings in
full, uncited high-severity ones in the open with the reason they are
uncited, the rest folded away. A hidden marker lets the
next run find the comment and update it instead of adding another.

Everything the model wrote may quote the author's content, and a comment is
read by the forge, not only by people: no HTML, no @-mentions, no links or
images (a prompt-injected diff could plant a tracking pixel), and no line may
start with `/` (GitLab runs those as quick actions: /merge, /approve).
"""

import re
from typing import List

from semantic_diff.formatters.markdown_formatter import escape_md
from semantic_diff.models import RiskLevel
from semantic_diff.review.markdown import SEVERITY_ORDER, code_span
from semantic_diff.review.report import Finding, ReviewReport

MARKER = "<!-- semantic-diff:review -->"

SERIOUS = (RiskLevel.HIGH, RiskLevel.CRITICAL)

ICONS = {"low": "🔹", "medium": "⚠️", "high": "🔶", "critical": "🔴"}


def comment_text(text: str) -> str:
    # One notion of a line: str.splitlines also breaks on \r, \u2028 and others,
    # which ^ in the pattern below would not see
    text = "\n".join(escape_md(text).replace("@", "@\u200b").splitlines())
    # No links or images under the token owner's name: [..](..) and ![..](..)
    # lose their brackets, bare URLs their scheme separator
    # (backslashes first: a model-written one would otherwise unescape a bracket)
    text = text.replace("\\", "\\\\")
    text = re.sub(r"([\[\]])", r"\\\1", text)
    text = re.sub(r"(?i)\b(https?|ftp|www)(:|\.)", "\\1\u200b\\2", text)
    # A backslash keeps the slash visible and the line out of quick actions
    return re.sub(r"(?m)^(\s*)/", r"\1\\/", text)


def one_line(text: str) -> str:
    return " ".join(comment_text(text).split())


def comment_body(report: ReviewReport) -> str:
    verdict = (report.verdict or "not submitted").replace("_", " ")
    if not report.stats.submitted:
        risk = "incomplete"
    else:
        risk = report.risk_level.value if report.risk_level else "none"
    lines = [
        MARKER,
        "## 🔍 Semantic Diff Review",
        "",
        f"**Verdict:** {verdict} · **Gate risk:** {risk} "
        "*(from cited findings only; uncited observations never gate)*",
        "",
    ]
    if report.verdict_note:
        proposed = (report.submitted_verdict or "none").replace("_", " ")
        lines += [f"> The reviewer proposed **{proposed}**: {one_line(report.verdict_note)}.", ""]
    if not report.stats.submitted:
        lines += ["> ⚠ Incomplete review: the model did not submit a review.", ""]
    lines += ["### Summary", "", comment_text(report.summary), ""]

    serious = [f for f in report.uncited if f.severity in SERIOUS]
    rest = [f for f in report.uncited if f.severity not in SERIOUS]
    if serious:
        lines += [
            f"> ⚠ {len(serious)} high-severity finding(s) below are uncited: they do not "
            "change the gate risk, but read them.",
            "",
        ]

    if report.findings:
        lines += [f"### Findings ({len(report.findings)}, cited)", ""]
        for finding in _ranked(report.findings):
            lines += _finding(finding)
    if serious:
        lines += [f"### Uncited high-severity findings ({len(serious)}, never gate)", ""]
        for finding in _ranked(serious):
            lines += _finding(finding)
    if rest:
        lines += [
            f"<details><summary>Other uncited observations ({len(rest)}, never gate)</summary>",
            "",
        ]
        for finding in _ranked(rest):
            lines += _finding(finding)
        lines += ["</details>", ""]

    cov = report.diff_coverage
    if cov.percent < 100:
        lines += [f"> Diff coverage: {cov.percent}% of changed lines shown up front", ""]
    lines += [
        "---",
        f"*Reviewed by semantic-diff ({one_line(report.review_model)}) "
        f"at {code_span(report.change_set.head_sha[:8])}*",
    ]
    return "\n".join(lines)


def no_changes_body() -> str:
    return "\n".join(
        [
            MARKER,
            "## 🔍 Semantic Diff Review",
            "",
            "No changes to review on the latest run: the earlier review no longer applies.",
        ]
    )


def _ranked(findings: List[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER.index(f.severity))


def _finding(finding: Finding) -> List[str]:
    where = code_span(f"{finding.file}:{finding.line}")
    severity = finding.severity.value
    head = f"- {ICONS[severity]} **[{severity}]** {where} {one_line(finding.title)}"
    if finding.uncited_reason is None:
        head += f" — {code_span(finding.rule_id or '')}, {one_line(finding.source or '')}"
    lines = [head, "", _indented(comment_text(finding.explanation))]
    if finding.suggestion:
        lines += ["", _indented(f"**Suggestion:** {comment_text(finding.suggestion)}")]
    if finding.uncited_reason is not None:
        lines += ["", _indented(f"*{why_uncited(finding)}*")]
    return lines + [""]


def why_uncited(finding: Finding) -> str:
    """The one reason a reader needs to weigh an uncited finding, plus the
    checks it did pass: "uncited" alone reads as "wrong"."""
    if finding.citation not in ("head", "base"):
        return "Uncited: the cited line does not exist; check it by hand."
    if not finding.seen:
        return "Uncited: the reviewer never opened this file; treat it as a guess."
    passed = "The cited line exists and the reviewer read the file"
    if finding.uncited_reason == "no_rule":
        return f"Uncited: no rule card backs it (or no rule corpus is configured). {passed}."
    if finding.uncited_reason == "unknown_rule_id":
        rule = " ".join((finding.rule_id or "").split())
        return (
            f"Uncited: it cites a rule that is not in the corpus ({comment_text(rule)}). {passed}."
        )
    return (
        "Uncited: its quoted evidence was not found in the diff next to the cited line. "
        f"{passed}."
    )


def _indented(text: str) -> str:
    # Continuation of the list item, so a model-written line cannot open a block
    return "\n".join(f"  {line}" for line in text.splitlines())
