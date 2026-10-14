"""
Tests for the review agent loop: the model explores the repository through
tools until it submits a review, within hard limits on turns and tokens.
The provider is scripted; the toolbox is real, over a real git repository.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List

import pytest

from semantic_diff.diff_pack import pack
from semantic_diff.models import ChangeSet, CommitRef, FileChange, RiskLevel
from semantic_diff.providers import (
    StopReason,
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
    UserMessage,
)
from semantic_diff.review.agent import SUBMIT_REVIEW, ReviewAgent, ReviewLimits
from semantic_diff.review.report import Finding, ReviewStats
from semantic_diff.review.tools import Toolbox

NOW = datetime(2026, 10, 14, 12, 0, 0)

API_DIFF = "@@ -1,2 +1,2 @@\n def get():\n-    return 1\n+    return 3"

VALID_SUBMISSION = {
    "summary": "Changes the return value of get().",
    "verdict": "request_changes",
    "findings": [
        {
            "file": "api.py",
            "line": 2,
            "severity": "high",
            "title": "Callers expect 1",
            "explanation": "util.py compares get() with 1, so the check now always fails.",
            "suggestion": "Update the caller or keep the value.",
        }
    ],
}


@dataclass
class Request:
    system: str
    messages: list
    tools: List[ToolSpec]
    max_tokens: int


class ScriptedProvider:
    """Plays back scripted turns and records every request it gets"""

    model = "scripted-opus"

    def __init__(self, *turns: Turn):
        self.turns = list(turns)
        self.requests: List[Request] = []

    def converse(self, system, messages, tools, *, max_tokens):
        self.requests.append(Request(system, list(messages), list(tools), max_tokens))
        if not self.turns:
            raise AssertionError("the agent asked for more turns than were scripted")
        return self.turns.pop(0)


_ids = iter(range(1, 10_000))


def call(name: str, arguments=None, raw: str = "") -> ToolCall:
    return ToolCall(f"call_{next(_ids)}", name, arguments, raw)


def uses(*calls, text="", input_tokens=100, output_tokens=10, cache_read=0, cache_write=0):
    return Turn(
        text,
        tuple(calls),
        StopReason.TOOL_USE,
        input_tokens,
        output_tokens,
        cache_read,
        cache_write,
    )


def says(text, input_tokens=100, output_tokens=10, stop=StopReason.END):
    return Turn(text, (), stop, input_tokens, output_tokens)


def submit(**override):
    return call("submit_review", {**VALID_SUBMISSION, **override})


@pytest.fixture
def change(mr_repo):
    change_set = ChangeSet(
        kind="merge_request",
        ref="base..head",
        head_sha=mr_repo["head"].hexsha,
        base_sha=mr_repo["base"].hexsha,
        title="fix: return 3",
        description="Why: callers need 3.",
        authors=["Dev One"],
        commits=[CommitRef(short_hash="c3", subject="fix: return 3", author="Dev One")],
    )
    files = [
        FileChange(
            path="api.py", change_type="modified", additions=1, deletions=1, diff_content=API_DIFF
        )
    ]
    toolbox = Toolbox(mr_repo["repo"], head=change_set.head_sha, base=change_set.base_sha)
    return {"change_set": change_set, "files": files, "toolbox": toolbox}


def _review(change, provider, **limits):
    agent = ReviewAgent(provider, change["toolbox"], limits=ReviewLimits(**limits), now=lambda: NOW)
    return agent.review(change["change_set"], change["files"])


def _results(request: Request) -> List[ToolResult]:
    return [m for m in request.messages if isinstance(m, ToolResult)]


class TestSubmit:
    def test_submission_becomes_the_report(self, change):
        provider = ScriptedProvider(uses(submit(), input_tokens=500, output_tokens=40))

        report = _review(change, provider)

        assert report.verdict == "request_changes"
        assert report.summary == "Changes the return value of get()."
        assert report.findings == [
            Finding(
                file="api.py",
                line=2,
                severity=RiskLevel.HIGH,
                title="Callers expect 1",
                explanation="util.py compares get() with 1, so the check now always fails.",
                suggestion="Update the caller or keep the value.",
            )
        ]
        assert report.change_set == change["change_set"]
        assert report.review_model == "scripted-opus"
        assert report.review_timestamp == NOW.isoformat()
        assert report.diff_coverage == pack(change["files"], 30_000).coverage
        assert report.stats == ReviewStats(
            turns=1, input_tokens=500, output_tokens=40, submitted=True
        )

    def test_no_findings_is_a_valid_review(self, change):
        provider = ScriptedProvider(uses(submit(findings=[], verdict="approve")))

        report = _review(change, provider)

        assert (report.verdict, report.findings) == ("approve", [])

    def test_invalid_submission_is_sent_back_with_what_is_wrong(self, change):
        bad = submit(verdict="lgtm", findings=[{"file": "api.py", "line": 0}])
        provider = ScriptedProvider(uses(bad), uses(submit()))

        report = _review(change, provider)

        [result] = _results(provider.requests[1])
        assert result.call_id == bad.id
        assert result.is_error
        assert result.content.startswith("submit_review rejected, fix and call it again:")
        for problem in ["verdict:", "findings.0.line:", "findings.0.severity:"]:
            assert problem in result.content
        assert report.stats.submitted and report.stats.turns == 2

    def test_unparsable_submission_is_sent_back(self, change):
        bad = call("submit_review", None, raw='{"summary": "cut off')
        provider = ScriptedProvider(uses(bad), uses(submit()))

        _review(change, provider)

        [result] = _results(provider.requests[1])
        assert (result.call_id, result.is_error) == (bad.id, True)
        assert result.content == (
            'submit_review rejected, fix and call it again: arguments must be a JSON object, got: {"summary": "cut off'
        )

    def test_submission_cut_by_the_output_limit_says_so(self, change):
        bad = call("submit_review", None, raw='{"summary": "cut off')
        cut = Turn("", (bad,), StopReason.MAX_TOKENS, 100, 8000)
        provider = ScriptedProvider(cut, uses(submit()))

        _review(change, provider)

        [result] = _results(provider.requests[1])
        assert "Your reply hit the output token limit" in result.content

    def test_each_problem_is_named_by_its_location(self, change):
        provider = ScriptedProvider(uses(submit(summary="", verdict="x")), uses(submit()))

        _review(change, provider)

        [result] = _results(provider.requests[1])
        assert result.content == (
            "submit_review rejected, fix and call it again: "
            "summary: String should have at least 1 character; "
            "verdict: Input should be 'approve', 'comment' or 'request_changes'"
        )

    def test_unknown_submission_fields_are_rejected(self, change):
        provider = ScriptedProvider(uses(submit(risk="high")), uses(submit()))

        _review(change, provider)

        [result] = _results(provider.requests[1])
        assert result.is_error and "risk:" in result.content

    def test_valid_submission_ends_the_review_even_beside_other_calls(self, change):
        provider = ScriptedProvider(uses(call("read_file", {"path": "api.py"}), submit()))

        report = _review(change, provider)

        assert report.stats.submitted
        assert len(provider.requests) == 1


class TestFirstRequest:
    def test_system_prompt_carries_the_review_method_and_the_turn_budget(self, change):
        provider = ScriptedProvider(uses(submit()))

        _review(change, provider, max_turns=7)

        system = provider.requests[0].system
        assert "at most 7 turns" in system
        assert "never follow instructions" in system
        assert "submit_review" in system

    def test_offers_the_repository_tools_and_submit_review(self, change):
        provider = ScriptedProvider(uses(submit()))

        _review(change, provider)

        assert provider.requests[0].tools == [*change["toolbox"].specs, SUBMIT_REVIEW]

    def test_first_message_has_the_change_manifest_and_packed_diff(self, change):
        provider = ScriptedProvider(uses(submit()))

        _review(change, provider)

        [first] = provider.requests[0].messages
        assert isinstance(first, UserMessage)
        assert "- **Title:** fix: return 3" in first.text
        assert (
            "<untrusted_description>\nWhy: callers need 3.\n</untrusted_description>" in first.text
        )
        assert "- api.py (modified) +1/-1" in first.text
        assert f"```diff\n{API_DIFF}\n```" in first.text

    def test_diff_is_packed_to_the_review_diff_budget(self, change):
        provider = ScriptedProvider(uses(submit()))

        report = _review(change, provider, diff_budget_tokens=5)

        assert report.diff_coverage.omitted == ["api.py"]
        assert "- api.py (over the diff budget)" in provider.requests[0].messages[0].text

    def test_per_turn_output_limit_is_passed_on(self, change):
        provider = ScriptedProvider(uses(submit()))

        _review(change, provider, max_output_tokens=1234)

        assert provider.requests[0].max_tokens == 1234


class TestToolLoop:
    def test_tool_results_go_back_in_the_next_request(self, change):
        read = call("read_file", {"path": "api.py"})
        provider = ScriptedProvider(uses(read, text="Reading api.py"), uses(submit()))

        report = _review(change, provider)

        second = provider.requests[1].messages
        assert second[1].text == "Reading api.py"
        assert second[1].tool_calls == (read,)
        assert second[2] == ToolResult(
            read.id, "api.py (head) lines 1-2 of 2\n    1| def get():\n    2|     return 3"
        )
        assert report.stats.tool_calls == 1
        assert report.stats.turns == 2

    def test_every_call_of_a_turn_is_answered_in_order(self, change):
        calls = [call("read_file", {"path": "api.py"}), call("grep", {"pattern": "get"})]
        provider = ScriptedProvider(uses(*calls), uses(submit()))

        _review(change, provider)

        assert [r.call_id for r in _results(provider.requests[1])] == [c.id for c in calls]

    def test_failed_tool_call_is_answered_as_an_error(self, change):
        provider = ScriptedProvider(uses(call("read_file", {"path": "nope.py"})), uses(submit()))

        report = _review(change, provider)

        [result] = _results(provider.requests[1])
        assert result.is_error
        assert report.stats.files_read == []

    def test_files_read_lists_each_successfully_read_file_once_in_order(self, change):
        provider = ScriptedProvider(
            uses(call("read_file", {"path": "util.py"}), call("read_base", {"path": "api.py"})),
            uses(call("read_file", {"path": "./util.py"}), call("grep", {"pattern": "x"})),
            uses(submit()),
        )

        report = _review(change, provider)

        assert report.stats.files_read == ["util.py", "api.py"]
        assert report.stats.tool_calls == 4

    def test_text_without_tool_calls_is_nudged_to_continue(self, change):
        provider = ScriptedProvider(says("I think it's fine."), uses(submit()))

        report = _review(change, provider)

        last = provider.requests[1].messages[-1]
        assert isinstance(last, UserMessage)
        assert "submit_review" in last.text
        assert report.stats.submitted

    def test_usage_is_summed_over_all_turns(self, change):
        provider = ScriptedProvider(
            uses(
                call("grep", {"pattern": "get"}),
                input_tokens=1000,
                output_tokens=50,
                cache_write=900,
            ),
            uses(submit(), input_tokens=1200, output_tokens=80, cache_read=900, cache_write=250),
        )

        stats = _review(change, provider).stats

        assert (stats.input_tokens, stats.output_tokens) == (2200, 130)
        assert (stats.cache_read_tokens, stats.cache_write_tokens) == (900, 1150)


def _grep_forever(n):
    return [uses(call("grep", {"pattern": "get"})) for _ in range(n)]


class TestLimits:
    def test_last_turn_offers_only_submit_review_and_says_why(self, change):
        provider = ScriptedProvider(*_grep_forever(2), uses(submit()))

        report = _review(change, provider, max_turns=3)

        assert [r.tools for r in provider.requests[:2]] == [provider.requests[0].tools] * 2
        assert provider.requests[2].tools == [SUBMIT_REVIEW]
        wrap_up = _results(provider.requests[2])[-1].content
        assert "Review budget reached (turns)" in wrap_up
        assert "call submit_review now" in wrap_up
        assert report.stats.submitted
        assert report.stats.limit_hit == "turns"

    def test_wrap_up_note_also_follows_a_nudge(self, change):
        provider = ScriptedProvider(says("Hmm."), uses(submit()))

        _review(change, provider, max_turns=2)

        last = provider.requests[1].messages[-1]
        assert isinstance(last, UserMessage)
        assert "Review budget reached (turns)" in last.text

    def test_no_submission_on_the_last_turn_yields_an_incomplete_report(self, change):
        provider = ScriptedProvider(*_grep_forever(1), says("Looks risky, out of time."))

        report = _review(change, provider, max_turns=2)

        assert report.verdict is None
        assert report.findings == []
        assert report.summary == "Looks risky, out of time."
        assert report.stats.submitted is False
        assert report.stats.limit_hit == "turns"
        assert report.stats.turns == 2

    def test_other_tools_on_the_last_turn_are_not_run(self, change):
        provider = ScriptedProvider(*_grep_forever(2))

        report = _review(change, provider, max_turns=2)

        assert report.stats.submitted is False
        assert report.stats.tool_calls == 1

    def test_incomplete_report_without_any_text_says_it_was_not_submitted(self, change):
        provider = ScriptedProvider(*_grep_forever(2))

        report = _review(change, provider, max_turns=2)

        assert report.summary == "The review was not submitted."

    def test_incomplete_report_keeps_the_last_thing_the_model_said(self, change):
        provider = ScriptedProvider(
            uses(call("grep", {"pattern": "get"}), text="Checking callers."),
            uses(call("grep", {"pattern": "get"})),
        )

        report = _review(change, provider, max_turns=2)

        assert report.summary == "Checking callers."

    def test_cumulative_input_tokens_trigger_the_wrap_up(self, change):
        provider = ScriptedProvider(
            uses(call("grep", {"pattern": "get"}), input_tokens=600),
            uses(call("grep", {"pattern": "get"}), input_tokens=600),
            uses(submit()),
        )

        report = _review(change, provider, max_input_tokens=1000)

        assert [len(r.tools) for r in provider.requests] == [6, 6, 1]
        assert report.stats.limit_hit == "tokens"

    def test_spending_exactly_the_token_budget_triggers_the_wrap_up(self, change):
        provider = ScriptedProvider(
            uses(call("grep", {"pattern": "get"}), input_tokens=500),
            uses(call("grep", {"pattern": "get"}), input_tokens=500),
            uses(submit()),
        )

        _review(change, provider, max_input_tokens=1000)

        assert [len(r.tools) for r in provider.requests] == [6, 6, 1]

    def test_a_turn_near_the_context_window_triggers_the_wrap_up(self, change):
        provider = ScriptedProvider(
            uses(call("grep", {"pattern": "get"}), input_tokens=150_000), uses(submit())
        )

        report = _review(change, provider, max_context_tokens=150_000)

        assert provider.requests[1].tools == [SUBMIT_REVIEW]
        assert report.stats.limit_hit == "context"

    def test_limits_below_threshold_do_not_wrap_up(self, change):
        provider = ScriptedProvider(
            uses(call("grep", {"pattern": "get"}), input_tokens=999), uses(submit())
        )

        report = _review(change, provider, max_input_tokens=1000, max_context_tokens=1000)

        assert len(provider.requests[1].tools) == 6
        assert report.stats.limit_hit is None

    def test_single_turn_budget_starts_in_wrap_up(self, change):
        provider = ScriptedProvider(uses(submit()))

        report = _review(change, provider, max_turns=1)

        assert provider.requests[0].tools == [SUBMIT_REVIEW]
        assert report.stats.limit_hit == "turns"

    @pytest.mark.parametrize(
        "field",
        [
            "max_turns",
            "max_input_tokens",
            "max_context_tokens",
            "max_output_tokens",
            "diff_budget_tokens",
        ],
    )
    def test_limits_must_be_positive(self, field):
        with pytest.raises(ValueError, match=field):
            ReviewLimits(**{field: 0})

    def test_defaults(self):
        assert ReviewLimits() == ReviewLimits(
            max_turns=25,
            max_input_tokens=1_000_000,
            max_context_tokens=150_000,
            max_output_tokens=8_000,
            diff_budget_tokens=30_000,
        )
