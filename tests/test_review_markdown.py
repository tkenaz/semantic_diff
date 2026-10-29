"""
Tests for the review report as Markdown: findings riskiest first, each with
its checks spelled out, model text escaped, and an honest account of how the
review went.
"""

from datetime import datetime

import pytest

from semantic_diff.models import ChangeSet, DiffCoverage, RiskLevel
from semantic_diff.review.markdown import ReviewMarkdownFormatter
from semantic_diff.review.report import Finding, ReviewReport, ReviewStats


def _finding(severity="high", file="api.py", line=2, citation="head", seen=True, **override):
    return Finding(
        file=file,
        line=line,
        severity=RiskLevel(severity),
        title=override.pop("title", "Callers expect 1"),
        explanation=override.pop("explanation", "util.py compares get() with 1."),
        suggestion=override.pop("suggestion", None),
        citation=citation,
        seen=seen,
        **override,
    )


def _report(**override) -> ReviewReport:
    fields = dict(
        change_set=ChangeSet(
            kind="merge_request",
            ref="abc1234..def5678",
            head_sha="def5678" + "0" * 33,
            base_sha="abc1234" + "0" * 33,
            title="fix: return 3",
        ),
        verdict="request_changes",
        summary="Changes get().",
        findings=[_finding()],
        stats=ReviewStats(
            turns=12,
            tool_calls=17,
            input_tokens=209_624,
            output_tokens=4_201,
            cache_read_tokens=167_571,
            cache_write_tokens=42_039,
            files_read=["api.py", "util.py"],
            submitted=True,
        ),
        diff_coverage=DiffCoverage(budget_tokens=30_000, shown_lines=10, total_lines=10),
        review_model="claude-opus-4.6",
        review_timestamp="2026-10-14T12:00:00",
    )
    return ReviewReport(**{**fields, **override})


def _md(**override) -> str:
    return ReviewMarkdownFormatter().format(_report(**override))


class TestHeader:
    def test_names_the_change_verdict_and_model(self):
        lines = _md().splitlines()

        assert lines[0] == "# Review: abc1234..def5678"
        assert "**fix: return 3**" in lines
        assert "**Verdict:** request changes · claude-opus-4.6 · 2026-10-14T12:00:00" in lines

    def test_title_is_escaped(self):
        cs = _report().change_set.model_copy(update={"title": "<img src=x>"})

        assert "**&lt;img src=x&gt;**" in _md(change_set=cs)

    def test_unsubmitted_review_is_flagged_as_incomplete(self):
        stats = _report().stats.model_copy(update={"submitted": False, "limit_hit": "turns"})

        md = _md(verdict=None, findings=[], stats=stats)

        assert "**Verdict:** none" in md
        assert (
            "> ⚠ **Incomplete review:** the model did not submit a review (stopped by the turn limit)."
            in md
        )

    @pytest.mark.parametrize(
        "limit, words",
        [("turns", "turn limit"), ("tokens", "token budget"), ("context", "context size limit")],
    )
    def test_review_wrapped_up_early_says_by_what(self, limit, words):
        stats = _report().stats.model_copy(update={"limit_hit": limit})

        assert f"> ⚠ Wrapped up early by the {words}: parts of the change may be unchecked." in _md(
            stats=stats
        )

    def test_complete_review_has_no_warning(self):
        assert "⚠" not in _md()


class TestFindings:
    def test_riskiest_first_numbered_with_location(self):
        md = _md(
            findings=[
                _finding("low", title="Typo"),
                _finding("critical", file="db.py", line=7, title="Data loss"),
                _finding("medium", title="Slow"),
            ]
        )

        headings = [line for line in md.splitlines() if line.startswith("### ")]
        assert headings == [
            "### 1. 🔥 CRITICAL · `db.py:7` · Data loss",
            "### 2. ⚠️ MEDIUM · `api.py:2` · Slow",
            "### 3. ✓ LOW · `api.py:2` · Typo",
        ]
        assert "## Findings (3)" in md

    def test_explanation_and_suggestion(self):
        md = _md(findings=[_finding(suggestion="Keep the value.")])

        assert "util.py compares get() with 1." in md
        assert "**Suggestion:** Keep the value." in md

    def test_no_suggestion_no_line(self):
        assert "**Suggestion:**" not in _md()

    def test_no_findings(self):
        md = _md(findings=[], verdict="approve")

        assert "## Findings (0)" in md
        assert "No cited findings." in md

    @pytest.mark.parametrize(
        "citation, note",
        [
            ("base", "> Cites code as it was before the change (removed or moved)."),
            ("no_such_line", "> ⚠ api.py has no line 2: check this finding by hand."),
            ("no_such_file", "> ⚠ api.py does not exist: check this finding by hand."),
        ],
    )
    def test_citation_problems_are_spelled_out(self, citation, note):
        assert note in _md(findings=[_finding(citation=citation)])

    def test_finding_about_a_file_the_model_never_saw(self):
        md = _md(findings=[_finding(seen=False)])

        assert "> ⚠ The reviewer never opened this file: treat this finding as a guess." in md

    def test_verified_finding_carries_no_notes(self):
        assert "> " not in _md().split("## Findings")[1].split("## How")[0]

    def test_model_text_is_escaped(self):
        md = _md(
            summary="<script>x</script>",
            findings=[_finding(title="<b>t</b>", explanation="<img>", suggestion="<a>")],
        )

        for raw in ["<script>", "<b>", "<img>", "<a>"]:
            assert raw not in md

    def test_backticks_in_path_cannot_close_the_code_span(self):
        # CommonMark: a code span opened by N backticks ends only at a run of exactly N
        md = _md(findings=[_finding(file="a`b``c.py")])

        assert "· ```a`b``c.py:2``` ·" in md

    def test_path_starting_with_a_backtick_is_padded(self):
        md = _md(findings=[_finding(file="`x.py")])

        assert "· `` `x.py:2 `` ·" in md


class TestChannels:
    def test_cited_finding_names_its_rule_and_quotes_its_evidence(self):
        md = _md(
            findings=[
                _finding(
                    rule_id="ASVS-8.2.1",
                    source="OWASP ASVS 5.0 §8.2.1 (CC BY-SA 4.0)",
                    evidence='+@router.post("/export")',
                )
            ],
            risk_level=RiskLevel.HIGH,
        )

        assert "**Rule:** `ASVS-8.2.1` — OWASP ASVS 5.0 §8.2.1 (CC BY-SA 4.0)" in md
        assert '```\n+@router.post("/export")\n```' in md
        assert "**Gate risk:** high" in md

    def test_no_uncited_section_without_uncited_observations(self):
        assert "## Uncited observations" not in _md()

    def test_invented_rule_id_is_called_out(self):
        md = _md(
            findings=[],
            uncited=[_finding(rule_id="GHOST-1", source="x", uncited_reason="unknown_rule_id")],
        )

        assert (
            "> ⚠ Cites rule `GHOST-1`, which is not in the configured corpus: "
            "treat the citation as invented." in md
        )

    def test_an_invented_rule_id_cannot_break_out_of_its_code_span(self):
        md = _md(
            findings=[],
            uncited=[
                _finding(rule_id="X`\n# Approved", source="x", uncited_reason="unknown_rule_id")
            ],
        )

        assert "> ⚠ Cites rule ``X` # Approved``, which is not in the configured corpus" in md
        assert "\n# Approved" not in md

    def test_failed_evidence_is_called_out(self):
        md = _md(
            findings=[],
            uncited=[
                _finding(
                    rule_id="ASVS-8.2.1",
                    source="OWASP ASVS 5.0 §8.2.1",
                    evidence="not in the diff",
                    uncited_reason="no_evidence",
                )
            ],
        )

        assert "but the evidence did not check out" in md

    def test_plain_observation_carries_no_rule_notes(self):
        md = _md(findings=[], uncited=[_finding(uncited_reason="no_rule")])

        assert "treat the citation as invented" not in md
        assert "evidence did not check out (cited line" not in md


class TestHowItWent:
    def test_turns_tools_tokens_and_files(self):
        md = _md()

        assert "- 12 turns, 17 tool calls" in md
        assert (
            "- Tokens: 209,624 in (167,571 read from cache, 42,039 written to cache), 4,201 out"
            in md
        )
        assert "- Files read: api.py, util.py" in md
        assert "- Diff coverage: 100% of changed lines shown up front (budget 30,000 tokens)" in md

    def test_no_files_read(self):
        stats = _report().stats.model_copy(update={"files_read": []})

        assert "- Files read: none beyond the diff" in _md(stats=stats)

    def test_partial_diff_lists_what_was_not_shown(self):
        coverage = DiffCoverage(
            budget_tokens=10, shown_lines=1, total_lines=4, omitted=["big.py"], noise=["x.lock"]
        )

        md = _md(diff_coverage=coverage)

        assert "- Diff coverage: 25% of changed lines shown up front (budget 10 tokens)" in md
        assert "  - Not shown up front: big.py" in md
        assert "  - Skipped (lock/generated/binary): x.lock" in md

    def test_file_paths_are_escaped(self):
        stats = _report().stats.model_copy(update={"files_read": ["__init__.py"]})

        assert "- Files read: \\_\\_init\\_\\_.py" in _md(stats=stats)


class TestWholeDocument:
    def test_layout(self):
        coverage = DiffCoverage(
            budget_tokens=10, shown_lines=1, total_lines=4, trimmed=["a.py"], omitted=["big.py"]
        )
        stats = _report().stats.model_copy(update={"limit_hit": "tokens", "files_read": []})

        md = _md(
            diff_coverage=coverage,
            stats=stats,
            risk_level=RiskLevel.HIGH,
            findings=[
                _finding("high", suggestion="Keep 1."),
            ],
            uncited=[
                _finding(
                    "low",
                    citation="no_such_line",
                    seen=False,
                    title="Guess",
                    uncited_reason="no_rule",
                ),
            ],
        )

        assert md == (
            "# Review: abc1234..def5678\n"
            "\n"
            "**fix: return 3**\n"
            "\n"
            "**Verdict:** request changes · claude-opus-4.6 · 2026-10-14T12:00:00\n"
            "\n"
            "**Gate risk:** high — from cited findings only; uncited observations never gate.\n"
            "\n"
            "> ⚠ Wrapped up early by the token budget: parts of the change may be unchecked.\n"
            "\n"
            "## Summary\n"
            "\n"
            "Changes get().\n"
            "\n"
            "## Findings (1)\n"
            "\n"
            "### 1. ⚡ HIGH · `api.py:2` · Callers expect 1\n"
            "\n"
            "util.py compares get() with 1.\n"
            "\n"
            "**Suggestion:** Keep 1.\n"
            "\n"
            "## Uncited observations (1)\n"
            "\n"
            "No rule card backs these (or their evidence did not check out). "
            "Informational: they never flip a pass to a fail.\n"
            "\n"
            "### 1. ✓ LOW · `api.py:2` · Guess\n"
            "\n"
            "util.py compares get() with 1.\n"
            "\n"
            "> ⚠ api.py has no line 2: check this finding by hand.\n"
            "\n"
            "> ⚠ The reviewer never opened this file: treat this finding as a guess.\n"
            "\n"
            "## How the review went\n"
            "\n"
            "- 12 turns, 17 tool calls\n"
            "- Tokens: 209,624 in (167,571 read from cache, 42,039 written to cache), 4,201 out\n"
            "- Files read: none beyond the diff\n"
            "- Diff coverage: 25% of changed lines shown up front (budget 10 tokens)\n"
            "  - Trimmed to whole hunks: a.py\n"
            "  - Not shown up front: big.py\n"
        )

    def test_no_findings_and_not_submitted_without_a_limit(self):
        stats = _report().stats.model_copy(update={"submitted": False})

        md = _md(verdict=None, findings=[], stats=stats)

        assert (
            "**Verdict:** none · claude-opus-4.6 · 2026-10-14T12:00:00\n"
            "\n"
            "**Gate risk:** incomplete — from cited findings only; uncited observations never gate.\n"
            "\n"
            "> ⚠ **Incomplete review:** the model did not submit a review.\n"
            "\n"
            "## Summary\n"
            "\n"
            "Changes get().\n"
            "\n"
            "## Findings (0)\n"
            "\n"
            "No cited findings.\n"
            "\n"
            "## How the review went\n"
        ) in md

    def test_several_paths_are_comma_separated(self):
        coverage = DiffCoverage(budget_tokens=1, shown_lines=0, total_lines=2, omitted=["a", "b"])

        assert "  - Not shown up front: a, b" in _md(diff_coverage=coverage)


class TestSave:
    def test_writes_a_review_file_named_after_the_head(self, tmp_path):
        path = ReviewMarkdownFormatter(now=lambda: datetime(2026, 10, 14, 12, 0, 5)).save(
            _report(), tmp_path / "reports"
        )

        assert path == tmp_path / "reports" / "review_def56780_20261014_120005.md"
        assert path.read_text(encoding="utf-8") == _md()

    def test_creates_nested_directories_and_reuses_existing_ones(self, tmp_path):
        target = tmp_path / "a" / "b"
        formatter = ReviewMarkdownFormatter(now=lambda: datetime(2026, 10, 14, 12, 0, 5))

        formatter.save(_report(), target)
        second = formatter.save(_report(summary="again"), target)

        assert "again" in second.read_text(encoding="utf-8")
