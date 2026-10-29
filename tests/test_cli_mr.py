"""
Tests for `semantic-diff mr` - analyzing a whole merge request range, locally
(--base/--head) or inside a GitLab MR pipeline (--gitlab-env).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from semantic_diff.cli import main


@pytest.fixture
def analyzer(mock_mr_analysis):
    """Mocked analyzer class; the provider factory is mocked too (no API)."""
    with (
        patch("semantic_diff.cli.build_provider"),
        patch("semantic_diff.cli.LLMAnalyzer") as analyzer_class,
    ):
        analyzer_class.return_value.analyze.return_value = mock_mr_analysis
        yield analyzer_class


def _analyzed(analyzer):
    change_set, files, _context = analyzer.return_value.analyze.call_args.args
    return change_set, files


def _gitlab_env(mr_repo, **overrides):
    env = {
        "CI_MERGE_REQUEST_DIFF_BASE_SHA": mr_repo["base"].hexsha,
        "CI_COMMIT_SHA": mr_repo["head"].hexsha,
        "CI_MERGE_REQUEST_TITLE": "fix(platform): PROJ-7 return 3",
        "CI_MERGE_REQUEST_DESCRIPTION": "Why: the spec says 3.",
    }
    return {**env, **overrides}


class TestMrLocal:
    def test_analyzes_the_whole_range(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main, ["mr", "--base", "target", "--head", "feature", "--repo", mr_repo["path"]]
        )

        assert result.exit_code == 0, result.output
        change_set, files = _analyzed(analyzer)
        assert change_set.kind == "merge_request"
        assert change_set.base_sha == mr_repo["base"].hexsha
        assert change_set.head_sha == mr_repo["head"].hexsha
        assert [c.subject for c in change_set.commits] == [
            "feat: return 2",
            "feat: add util",
            "fix: return 3",
        ]
        assert sorted(f.path for f in files) == ["api.py", "util.py"]

    def test_title_falls_back_to_commit_count(self, mr_repo, analyzer):
        CliRunner().invoke(
            main, ["mr", "--base", "target", "--head", "feature", "--repo", mr_repo["path"]]
        )

        change_set, _ = _analyzed(analyzer)
        assert change_set.title.startswith("3 commits (")

    def test_title_and_description_file_are_used(self, mr_repo, analyzer, tmp_path):
        description = tmp_path / "mr.md"
        description.write_text("Because the spec says so.")

        CliRunner().invoke(
            main,
            [
                "mr",
                "--base",
                "target",
                "--head",
                "feature",
                "--repo",
                mr_repo["path"],
                "--title",
                "PROJ-7 return 3",
                "--description-file",
                str(description),
            ],
        )

        change_set, _ = _analyzed(analyzer)
        assert change_set.title == "PROJ-7 return 3"
        assert change_set.description == "Because the spec says so."

    def test_head_defaults_to_checked_out_head(self, mr_repo, analyzer):
        mr_repo["repo"].heads.feature.checkout()

        CliRunner().invoke(main, ["mr", "--base", "target", "--repo", mr_repo["path"]])

        change_set, _ = _analyzed(analyzer)
        assert change_set.head_sha == mr_repo["head"].hexsha

    def test_base_is_required_without_gitlab_env(self, mr_repo, analyzer):
        result = CliRunner().invoke(main, ["mr", "--repo", mr_repo["path"]])

        assert result.exit_code == 1
        assert "--base" in result.output
        analyzer.return_value.analyze.assert_not_called()

    def test_empty_range_exits_cleanly_without_calling_the_model(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main, ["mr", "--base", "feature", "--head", "feature", "--repo", mr_repo["path"]]
        )

        assert result.exit_code == 0
        assert "No changes found" in result.output
        analyzer.return_value.analyze.assert_not_called()

    def test_json_output(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main,
            ["mr", "--base", "target", "--head", "feature", "--repo", mr_repo["path"], "--json"],
        )

        assert json.loads(result.output)["change_set"]["kind"] == "merge_request"

    def test_save_writes_mr_report(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main,
            ["mr", "--base", "target", "--head", "feature", "--repo", mr_repo["path"], "--save"],
        )

        assert result.exit_code == 0, result.output
        reports = list((Path(mr_repo["path"]) / "semantic_diff_reports").glob("mr_*.md"))
        assert len(reports) == 1

    def test_model_flag_reaches_provider(self, mr_repo):
        with (
            patch("semantic_diff.cli.build_provider") as build_provider,
            patch("semantic_diff.cli.LLMAnalyzer"),
        ):
            CliRunner().invoke(
                main,
                [
                    "mr",
                    "--base",
                    "target",
                    "--head",
                    "feature",
                    "--repo",
                    mr_repo["path"],
                    "--model",
                    "claude-sonnet-4.6",
                ],
            )

        build_provider.assert_called_once_with(model="claude-sonnet-4.6")


class TestMrGitlabEnv:
    def test_takes_base_head_title_description_from_ci_variables(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main, ["mr", "--gitlab-env", "--repo", mr_repo["path"]], env=_gitlab_env(mr_repo)
        )

        assert result.exit_code == 0, result.output
        change_set, _ = _analyzed(analyzer)
        assert (change_set.base_sha, change_set.head_sha) == (
            mr_repo["base"].hexsha,
            mr_repo["head"].hexsha,
        )
        assert change_set.title == "fix(platform): PROJ-7 return 3"
        assert change_set.description == "Why: the spec says 3."

    def test_explicit_flags_override_ci_variables(self, mr_repo, analyzer):
        CliRunner().invoke(
            main,
            ["mr", "--gitlab-env", "--repo", mr_repo["path"], "--title", "override"],
            env=_gitlab_env(mr_repo),
        )

        change_set, _ = _analyzed(analyzer)
        assert change_set.title == "override"

    def test_outside_mr_pipeline_fails_clearly(self, mr_repo, analyzer):
        env = _gitlab_env(mr_repo, CI_MERGE_REQUEST_DIFF_BASE_SHA="")

        result = CliRunner().invoke(
            main, ["mr", "--gitlab-env", "--repo", mr_repo["path"]], env=env
        )

        assert result.exit_code == 1
        assert "merge request pipeline" in result.output

    def test_missing_base_commit_hints_at_shallow_clone(self, mr_repo, analyzer):
        env = _gitlab_env(mr_repo, CI_MERGE_REQUEST_DIFF_BASE_SHA="f" * 40)

        result = CliRunner().invoke(
            main, ["mr", "--gitlab-env", "--repo", mr_repo["path"]], env=env
        )

        assert result.exit_code == 1
        assert "Could not find commit" in result.output
        assert "GIT_DEPTH" in result.output


class TestMrJsonStdoutStaysParseable:
    """In CI, stdout of --json is piped into jq: diagnostics must go to stderr."""

    def test_empty_range_message_goes_to_stderr(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main,
            ["mr", "--base", "feature", "--head", "feature", "--repo", mr_repo["path"], "--json"],
        )

        assert result.stdout == ""
        assert "No changes found" in result.stderr

    def test_errors_go_to_stderr(self, mr_repo, analyzer):
        result = CliRunner().invoke(main, ["mr", "--repo", mr_repo["path"], "--json"])

        assert result.stdout == ""
        assert "--base" in result.stderr

    def test_mutually_exclusive_flags_error_goes_to_stderr(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main, ["mr", "--base", "target", "--repo", mr_repo["path"], "--brief", "--verbose"]
        )

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "mutually exclusive" in result.stderr

    def test_project_context_reaches_the_analyzer(self, mr_repo, analyzer):
        CliRunner().invoke(
            main, ["mr", "--base", "target", "--head", "feature", "--repo", mr_repo["path"]]
        )

        _change_set, _files, context = analyzer.return_value.analyze.call_args.args
        assert "python" in context["languages"]

    def test_save_message_goes_to_stderr_with_json(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main,
            [
                "mr",
                "--base",
                "target",
                "--head",
                "feature",
                "--repo",
                mr_repo["path"],
                "--json",
                "--save",
            ],
        )

        assert json.loads(result.stdout)["change_set"]["kind"] == "merge_request"
        assert "Report saved" in result.stderr

    def test_verbose_progress_goes_to_stderr_with_json(self, mr_repo, analyzer):
        result = CliRunner().invoke(
            main,
            [
                "mr",
                "--base",
                "target",
                "--head",
                "feature",
                "--repo",
                mr_repo["path"],
                "--json",
                "--verbose",
            ],
        )

        assert json.loads(result.stdout)["change_set"]["kind"] == "merge_request"
        assert "Found 2 changed files" in result.stderr


class TestMaxDiffTokens:
    def _invoke(self, mr_repo, *extra, env=None):
        with (
            patch("semantic_diff.cli.build_provider"),
            patch("semantic_diff.cli.LLMAnalyzer") as analyzer_class,
        ):
            CliRunner().invoke(
                main,
                ["mr", "--base", "target", "--head", "feature", "--repo", mr_repo["path"], *extra],
                env=env,
            )
        return analyzer_class.call_args.kwargs["max_diff_tokens"]

    def test_defaults_to_sixty_thousand(self, mr_repo):
        assert self._invoke(mr_repo) == 60_000

    def test_flag_sets_the_budget(self, mr_repo):
        assert self._invoke(mr_repo, "--max-diff-tokens", "20000") == 20_000

    def test_env_var_sets_the_budget(self, mr_repo):
        env = {"SEMANTIC_DIFF_MAX_DIFF_TOKENS": "30000"}

        assert self._invoke(mr_repo, env=env) == 30_000

    def test_analyze_command_accepts_it_too(self, mr_repo):
        with (
            patch("semantic_diff.cli.build_provider"),
            patch("semantic_diff.cli.LLMAnalyzer") as analyzer_class,
        ):
            CliRunner().invoke(
                main, ["analyze", "HEAD", "--repo", mr_repo["path"], "--max-diff-tokens", "500"]
            )

        assert analyzer_class.call_args.kwargs["max_diff_tokens"] == 500

    def test_non_positive_budget_is_a_usage_error(self, mr_repo):
        result = CliRunner().invoke(
            main,
            ["mr", "--base", "target", "--repo", mr_repo["path"], "--max-diff-tokens", "0"],
        )

        assert result.exit_code == 2
        assert "0 is not in the range" in result.stderr


class TestMaxOutputTokens:
    def _invoke(self, mr_repo, *extra, env=None):
        with (
            patch("semantic_diff.cli.build_provider"),
            patch("semantic_diff.cli.LLMAnalyzer") as analyzer_class,
        ):
            result = CliRunner().invoke(
                main,
                ["mr", "--base", "target", "--head", "feature", "--repo", mr_repo["path"], *extra],
                env=env,
            )
        return result, analyzer_class

    def test_defaults_to_thirty_two_thousand(self, mr_repo):
        _, analyzer_class = self._invoke(mr_repo)

        assert analyzer_class.call_args.kwargs["max_output_tokens"] == 32_000

    def test_flag_and_env(self, mr_repo):
        _, by_flag = self._invoke(mr_repo, "--max-output-tokens", "64000")
        _, by_env = self._invoke(mr_repo, env={"SEMANTIC_DIFF_MAX_OUTPUT_TOKENS": "48000"})

        assert by_flag.call_args.kwargs["max_output_tokens"] == 64_000
        assert by_env.call_args.kwargs["max_output_tokens"] == 48_000

    def test_non_positive_is_a_usage_error(self, mr_repo):
        result, _ = self._invoke(mr_repo, "--max-output-tokens", "0")

        assert result.exit_code == 2
        assert "0 is not in the range" in result.output
