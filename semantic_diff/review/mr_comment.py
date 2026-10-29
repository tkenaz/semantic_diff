"""
The review as one merge request comment: the verdict, the cited findings in
full, the uncited ones folded away as unverified. A hidden marker lets the
next run find the comment and update it instead of adding another.

Everything the model wrote may quote the author's content, and a comment is
read by the forge, not only by people: no HTML, no @-mentions, and no line
may start with `/` (GitLab runs those as quick actions: /merge, /approve).
"""

import re
from typing import List

from semantic_diff.formatters.markdown_formatter import escape_md
from semantic_diff.review.markdown import SEVERITY_ORDER, code_span
from semantic_diff.review.report import Finding, ReviewReport

MARKER = "<!-- semantic-diff:review -->"

ICONS = {"low": "✅", "medium": "⚠️", "high": "🔶", "critical": "🔴"}


def comment_text(text: str) -> str:
    text = escape_md(text).replace("@", "@​")
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

    if report.findings:
        lines += [f"### Findings ({len(report.findings)}, cited)", ""]
        for finding in _ranked(report.findings):
            lines += _finding(finding, cited=True)
    if report.uncited:
        lines += [
            "<details><summary>Unverified observations "
            f"({len(report.uncited)}): no rule card or the evidence did not check out; "
            "they never gate</summary>",
            "",
        ]
        for finding in _ranked(report.uncited):
            lines += _finding(finding, cited=False)
        lines += ["</details>", ""]

    cov = report.diff_coverage
    if cov.percent < 100:
        lines += [f"> Diff coverage: {cov.percent}% of changed lines shown up front", ""]
    lines += [
        "---",
        f"*Reviewed by [semantic-diff](https://github.com/tkenaz/semantic_diff) "
        f"({one_line(report.review_model)}) at {code_span(report.change_set.head_sha[:8])}*",
    ]
    return "\n".join(lines)


def _ranked(findings: List[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER.index(f.severity))


def _finding(finding: Finding, cited: bool) -> List[str]:
    where = code_span(f"{finding.file}:{finding.line}")
    severity = finding.severity.value
    head = f"- {ICONS[severity]} **[{severity}]** {where} {one_line(finding.title)}"
    if cited:
        head += f" — {code_span(finding.rule_id or '')}, {one_line(finding.source or '')}"
    lines = [head, "", _indented(comment_text(finding.explanation))]
    if finding.suggestion:
        lines += ["", _indented(f"**Suggestion:** {comment_text(finding.suggestion)}")]
    return lines + [""]


def _indented(text: str) -> str:
    # Continuation of the list item, so a model-written line cannot open a block
    return "\n".join(f"  {line}" for line in text.splitlines())
