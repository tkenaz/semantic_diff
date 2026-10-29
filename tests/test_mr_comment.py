"""
Tests for the review as an MR comment: marker first, verdict and cited
findings in full, uncited ones folded as unverified, and nothing the model
wrote can mention people, inject HTML or run a quick action.
"""

import pytest

from semantic_diff.review.mr_comment import MARKER, comment_body, why_uncited
from semantic_diff.review.report import ReviewStats
from tests.test_review_markdown import _finding, _report

CARD = dict(rule_id="api-contract", source="rules/api.md#contract")


def _body(**override) -> str:
    return comment_body(_report(**override))


class TestLayout:
    def test_starts_with_the_marker(self):
        assert _body().splitlines()[0] == MARKER

    def test_names_verdict_gate_risk_and_head(self):
        body = _body(findings=[_finding(**CARD)], risk_level="high")

        assert "**Verdict:** request changes · **Gate risk:** high" in body
        assert "at `def56780`" in body

    def test_cited_findings_carry_rule_explanation_and_suggestion(self):
        body = _body(findings=[_finding(suggestion="Return 1 again.", **CARD)])

        assert "### Findings (1, cited)" in body
        assert "`api.py:2` Callers expect 1 — `api-contract`, rules/api.md#contract" in body
        assert "  util.py compares get() with 1." in body
        assert "  **Suggestion:** Return 1 again." in body

    def test_uncited_high_findings_stay_in_the_open_with_a_warning(self):
        body = _body(findings=[], uncited=[_finding(uncited_reason="no_rule")])

        assert "> ⚠ 1 high-severity finding(s) below are uncited" in body
        assert "### Uncited high-severity findings (1, never gate)" in body
        assert "<details>" not in body
        assert "Callers expect 1" in body

    def test_lower_uncited_findings_are_folded(self):
        body = _body(findings=[], uncited=[_finding(severity="medium", uncited_reason="no_rule")])

        before, folded = body.split("<details>", 1)
        assert "Callers expect 1" not in before
        assert "Other uncited observations (1, never gate)" in folded
        assert "high-severity" not in body

    def test_the_footer_has_no_link(self):
        footer = _body().splitlines()[-1]

        assert footer == "*Reviewed by semantic-diff (claude-opus-4.6) at `def56780`*"
        assert "http" not in footer

    def test_an_unsubmitted_review_says_so(self):
        body = _body(verdict=None, findings=[], stats=ReviewStats(submitted=False))

        assert "**Gate risk:** incomplete" in body
        assert "did not submit a review" in body


class TestModelTextIsInert:
    def test_a_line_starting_with_a_slash_is_not_a_quick_action(self):
        body = _body(summary="Looks fine.\n/merge\n  /approve")

        assert not any(line.lstrip().startswith("/") for line in body.splitlines())
        assert "\\/merge" in body

    @pytest.mark.parametrize("separator", ["\r", "\u2028", "\x0b", "\x1c"])
    def test_other_line_separators_cannot_start_a_quick_action(self, separator):
        finding = _finding(explanation=f"ok{separator}/merge", suggestion=f"x{separator}/approve")
        body = _body(findings=[finding], summary=f"fine{separator}/close")

        assert not any(line.lstrip().startswith("/") for line in body.splitlines())

    def test_mentions_and_html_are_neutralised(self):
        body = _body(summary="ping @owner <img src=x onerror=alert(1)>")

        assert "@owner" not in body
        assert "<img" not in body

    def test_a_multiline_explanation_stays_inside_its_list_item(self):
        finding = _finding(explanation="first\n# heading\n/close", **CARD)
        body = _body(findings=[finding])

        assert "  # heading" in body
        assert "\n# heading" not in body
        assert "  \\/close" in body


class TestWhyUncited:
    def _why(self, **override):
        return why_uncited(_finding(**override))

    def test_no_rule_says_so_and_what_did_check_out(self):
        why = self._why(uncited_reason="no_rule")

        assert "no rule card backs it (or no rule corpus is configured)" in why
        assert "The cited line exists and the reviewer read the file" in why

    def test_unknown_rule_names_it(self):
        assert "not in the corpus (made-up)" in self._why(
            uncited_reason="unknown_rule_id", rule_id="made-up"
        )

    def test_failed_evidence_is_told_apart_from_a_missing_card(self):
        why = self._why(uncited_reason="no_evidence", **CARD)

        assert "quoted evidence was not found in the diff" in why
        assert "no rule card" not in why

    def test_a_missing_line_or_an_unread_file_comes_first(self):
        assert "line does not exist" in self._why(uncited_reason="no_rule", citation="no_such_line")
        assert "never opened this file" in self._why(uncited_reason="no_rule", seen=False)

    def test_the_reason_is_printed_under_the_finding(self):
        body = _body(findings=[], uncited=[_finding(uncited_reason="no_rule")])

        assert "  *Uncited: no rule card backs it" in body
