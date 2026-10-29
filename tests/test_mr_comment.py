"""
Tests for the review as an MR comment: marker first, verdict and cited
findings in full, uncited ones folded as unverified, and nothing the model
wrote can mention people, inject HTML or run a quick action.
"""

from semantic_diff.review.mr_comment import MARKER, comment_body
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

    def test_uncited_findings_are_folded_as_unverified(self):
        body = _body(findings=[], uncited=[_finding(uncited_reason="no_rule")])

        before, folded = body.split("<details>", 1)
        assert "Callers expect 1" not in before
        assert "Unverified observations (1)" in folded
        assert "Callers expect 1" in folded.split("</details>")[0]

    def test_an_unsubmitted_review_says_so(self):
        body = _body(verdict=None, findings=[], stats=ReviewStats(submitted=False))

        assert "**Gate risk:** incomplete" in body
        assert "did not submit a review" in body


class TestModelTextIsInert:
    def test_a_line_starting_with_a_slash_is_not_a_quick_action(self):
        body = _body(summary="Looks fine.\n/merge\n  /approve")

        assert not any(line.lstrip().startswith("/") for line in body.splitlines())
        assert "\\/merge" in body

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
