"""
Tests for `semantic-diff review` - the agentic merge request review. The agent
and its toolbox are real, over a real repository; only the model is scripted.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from semantic_diff.cli import main
from semantic_diff.gitlab_note import TOKEN_VARIABLE, NoteError
from semantic_diff.providers import AnthropicProvider, RetryingProvider, ToolResult
from tests.test_cli_mr import _gitlab_env
from tests.test_review_agent import ScriptedProvider, call, submit, uses

RANGE = ["--base", "target", "--head", "feature"]
NOTE_ENV = {
    "CI_API_V4_URL": "https://gitlab.example.org/api/v4",
    "CI_PROJECT_ID": "42",
    "CI_MERGE_REQUEST_IID": "5",
    TOKEN_VARIABLE: "fixture-token",
}


@pytest.fixture
def model():
    """A scripted model behind the provider factory; reads api.py, then submits"""
    provider = ScriptedProvider(uses(call("read_file", {"path": "api.py"})), uses(submit()))
    with patch("semantic_diff.cli.build_provider", return_value=provider) as factory:
        provider.factory = factory
        yield provider


def _review(mr_repo, *extra, env=None):
    return CliRunner().invoke(main, ["review", *RANGE, "--repo", mr_repo["path"], *extra], env=env)


class TestReview:
    def test_reviews_the_range_and_prints_the_report(self, mr_repo, model):
        result = _review(mr_repo)

        assert result.exit_code == 0, result.output
        assert "Review:" in result.stdout
        assert "Callers expect 1" in result.stdout
        first = model.requests[0].messages[0].text
        assert "feat: return 2" in first and "fix: return 3" in first

    def test_tools_read_the_merge_request_head(self, mr_repo, model):
        _review(mr_repo)

        [result] = [m for m in model.requests[1].messages if isinstance(m, ToolResult)]
        assert result.content.endswith("    2|     return 3")

    def test_json_output_is_the_report(self, mr_repo, model):
        result = _review(mr_repo, "--json")

        report = json.loads(result.stdout)
        assert report["schema_version"] == 2
        assert report["verdict"] == "request_changes"
        # No corpus: the finding is an uncited observation and nothing gates
        assert report["findings"] == []
        assert report["risk_level"] is None
        assert report["uncited"][0]["citation"] == "head"
        assert report["uncited"][0]["uncited_reason"] == "no_rule"
        assert report["stats"]["files_read"] == ["api.py"]

    def test_transcript_records_the_whole_conversation(self, mr_repo, model, tmp_path):
        path = tmp_path / "review.jsonl"

        result = _review(mr_repo, "--json", "--transcript", str(path))

        assert result.exit_code == 0, result.output
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        assert [line["role"] for line in lines] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert "hypothesis to test" in lines[0]["text"]
        assert lines[2]["tool_calls"][0]["name"] == "read_file"
        assert lines[3]["content"].endswith("    2|     return 3")
        assert lines[4]["tool_calls"][0]["name"] == "submit_review"

    def test_save_writes_a_review_report(self, mr_repo, model):
        result = _review(mr_repo, "--json", "--save")

        reports = list((Path(mr_repo["path"]) / "semantic_diff_reports").glob("review_*.md"))
        assert len(reports) == 1
        assert "Report saved" in result.stderr
        json.loads(result.stdout)

    def test_title_and_description_reach_the_model(self, mr_repo, model, tmp_path):
        description = tmp_path / "mr.md"
        description.write_text("Because the spec says so.")

        _review(mr_repo, "--title", "fix: PROJ-7 return 3", "--description-file", str(description))

        first = model.requests[0].messages[0].text
        assert "- **Title:** fix: PROJ-7 return 3" in first
        assert "Because the spec says so." in first

    def test_without_a_description_none_is_sent(self, mr_repo, model):
        _review(mr_repo)

        assert "untrusted_description" not in model.requests[0].messages[0].text

    def test_gitlab_env(self, mr_repo, model):
        result = CliRunner().invoke(
            main,
            ["review", "--gitlab-env", "--repo", mr_repo["path"], "--json"],
            env=_gitlab_env(mr_repo),
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["change_set"]["title"] == "fix(platform): PROJ-7 return 3"

    def test_gitlab_comment_posts_the_review_after_printing_it(self, mr_repo, model):
        with patch("semantic_diff.cli.MergeRequestNote") as note:
            note.return_value.upsert.return_value = "created"
            result = _review(mr_repo, "--json", "--gitlab-comment", env=NOTE_ENV)

        assert result.exit_code == 0, result.output
        json.loads(result.stdout)
        body, marker = note.return_value.upsert.call_args.args
        assert body.startswith(marker)
        assert "Callers expect 1" in body
        assert "MR comment created." in result.stderr

    def test_a_failed_comment_only_warns(self, mr_repo, model):
        with patch("semantic_diff.cli.MergeRequestNote") as note:
            note.return_value.upsert.side_effect = NoteError("POST /notes: HTTP 403")
            result = _review(mr_repo, "--json", "--gitlab-comment", env=NOTE_ENV)

        assert result.exit_code == 0, result.output
        assert "Warning: MR comment not posted: POST /notes: HTTP 403" in result.stderr
        json.loads(result.stdout)

    def test_a_comment_without_its_variables_only_warns(self, mr_repo, model):
        result = _review(mr_repo, "--json", "--gitlab-comment", env={TOKEN_VARIABLE: ""})

        assert result.exit_code == 0, result.output
        assert "MR comment not posted: not set:" in result.stderr

    def test_no_comment_without_the_flag(self, mr_repo, model):
        with patch("semantic_diff.cli.MergeRequestNote") as note:
            _review(mr_repo, "--json", env=NOTE_ENV)

        note.assert_not_called()

    def test_model_flag_reaches_the_provider(self, mr_repo, model):
        _review(mr_repo, "--model", "claude-opus-4.6")

        model.factory.assert_called_once_with(model="claude-opus-4.6")

    def test_base_is_required(self, mr_repo, model):
        result = CliRunner().invoke(main, ["review", "--repo", mr_repo["path"]])

        assert result.exit_code == 1
        assert "--base is required" in result.stderr

    def test_empty_range_does_not_call_the_model(self, mr_repo, model):
        result = CliRunner().invoke(
            main,
            ["review", "--base", "feature", "--head", "feature", "--repo", mr_repo["path"]],
        )

        assert result.exit_code == 0
        assert "No changes found" in result.stderr
        assert model.requests == []

    def test_provider_without_tool_calling_is_refused_clearly(self, mr_repo):
        class CompletionOnly:
            model = "m"

            def complete(self, prompt, *, max_tokens):
                raise AssertionError("review must not fall back to complete()")

        no_tools = RetryingProvider(CompletionOnly(), max_retries=1)
        with patch("semantic_diff.cli.build_provider", return_value=no_tools):
            result = _review(mr_repo)

        assert result.exit_code == 1
        assert "does not support tool calling" in result.stderr

    def test_the_anthropic_provider_is_accepted_for_review(self, mr_repo):
        # KEN-315: the reviewer must run where only ANTHROPIC_API_KEY exists
        provider = RetryingProvider(AnthropicProvider(client=Mock(), model="m"), max_retries=1)
        with patch("semantic_diff.cli.build_provider", return_value=provider):
            result = _review(mr_repo)

        assert "does not support tool calling" not in result.stderr

    def test_verbose_reports_progress_on_stderr(self, mr_repo, model):
        result = _review(mr_repo, "--json", "--verbose")

        json.loads(result.stdout)
        assert "Reviewing 2 changed files" in result.stderr

    def test_rules_corpus_enables_cited_findings(self, mr_repo, tmp_path):
        corpus = tmp_path / "corpus"
        (corpus / "rules").mkdir(parents=True)
        (corpus / "INDEX.md").write_text("| signal | tags |\n|---|---|\n| api | api |\n")
        (corpus / "rules" / "api.md").write_text(
            "### [TEST-1] Return values stay compatible\nsource: Public Standard §1\n"
        )
        cited = {
            "file": "api.py",
            "line": 2,
            "severity": "high",
            "title": "Callers expect 1",
            "explanation": "util.py compares get() with 1.",
            "rule_id": "TEST-1",
            "source": "Public Standard §1",
            "evidence": "+    return 3",
        }
        provider = ScriptedProvider(uses(submit(findings=[cited])))
        with patch("semantic_diff.cli.build_provider", return_value=provider):
            result = _review(mr_repo, "--rules", str(corpus), "--json")

        assert result.exit_code == 0, result.output
        report = json.loads(result.stdout)
        assert report["findings"][0]["rule_id"] == "TEST-1"
        assert report["risk_level"] == "high"
        assert "## Rule corpus" in provider.requests[0].messages[0].text

    def test_rules_must_name_an_existing_directory(self, mr_repo, model):
        result = _review(mr_repo, "--rules", "/no/such/dir")

        assert result.exit_code == 2
        assert "does not exist" in result.output


class TestReviewLimits:
    def test_max_turns_flag_and_env(self, mr_repo):
        for extra, env in [(["--max-turns", "1"], None), ([], {"SEMANTIC_DIFF_MAX_TURNS": "1"})]:
            provider = ScriptedProvider(uses(submit()))
            with patch("semantic_diff.cli.build_provider", return_value=provider):
                _review(mr_repo, *extra, env=env)

            assert "Review budget reached (turns)" in provider.requests[0].messages[0].text

    def test_default_turn_budget_is_twenty_five(self, mr_repo, model):
        _review(mr_repo)

        assert "at most 25 turns" in model.requests[0].system

    def test_input_token_budget_flag_and_env(self, mr_repo):
        for extra, env in [
            (["--max-input-tokens", "50"], None),
            ([], {"SEMANTIC_DIFF_MAX_INPUT_TOKENS": "50"}),
        ]:
            provider = ScriptedProvider(
                uses(call("grep", {"pattern": "get"}), input_tokens=100), uses(submit())
            )
            with patch("semantic_diff.cli.build_provider", return_value=provider):
                result = _review(mr_repo, "--json", *extra, env=env)

            assert json.loads(result.stdout)["stats"]["limit_hit"] == "tokens"

    def test_review_diff_budget_has_its_own_default_and_env(self, mr_repo):
        def budget(*extra, env=None):
            provider = ScriptedProvider(uses(submit()))
            with patch("semantic_diff.cli.build_provider", return_value=provider):
                result = _review(mr_repo, "--json", *extra, env=env)
            return json.loads(result.stdout)["diff_coverage"]["budget_tokens"]

        assert budget() == 30_000
        assert budget("--max-diff-tokens", "500") == 500
        assert budget(env={"SEMANTIC_DIFF_REVIEW_DIFF_TOKENS": "700"}) == 700
        # The one-shot analyzer's budget does not leak into reviews
        assert budget(env={"SEMANTIC_DIFF_MAX_DIFF_TOKENS": "900"}) == 30_000

    @pytest.mark.parametrize("flag", ["--max-turns", "--max-input-tokens", "--max-diff-tokens"])
    def test_non_positive_limits_are_usage_errors(self, mr_repo, model, flag):
        result = _review(mr_repo, flag, "0")

        assert result.exit_code == 2
        assert "0 is not in the range" in result.output
