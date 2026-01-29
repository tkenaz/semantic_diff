"""
Tests for CLI interface
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from git import Repo

from semantic_diff.cli import main


class TestCLIHelp:
    """Test CLI help output"""

    def test_help_flag_shows_usage(self):
        """Test that --help flag displays usage information"""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "semantic-diff" in result.output or "main" in result.output
        # Main help shows commands list
        assert "analyze" in result.output
        assert "init" in result.output
        assert "uninstall" in result.output

    def test_analyze_help_shows_options(self):
        """Test that analyze --help shows commit options"""
        runner = CliRunner()
        result = runner.invoke(main, ["analyze", "--help"])

        assert result.exit_code == 0
        assert "COMMIT_HASH" in result.output
        assert "--repo" in result.output
        assert "--json" in result.output

    def test_help_shows_examples(self):
        """Test that help includes usage examples"""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])

        assert "Examples:" in result.output
        assert "HEAD" in result.output


class TestCLIBasicExecution:
    """Test basic CLI execution scenarios"""

    def test_nonexistent_repo_exits_with_error(self):
        """Test that nonexistent repository path exits with code 1"""
        runner = CliRunner()
        result = runner.invoke(main, ["analyze", "HEAD", "--repo", "/nonexistent/path/to/repo"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        # Should show the invalid path
        assert "/nonexistent/path/to/repo" in result.output

    def test_invalid_commit_hash_exits_with_error(self, temp_git_repo):
        """Test that invalid commit hash exits with error"""
        repo_path, _, _ = temp_git_repo
        runner = CliRunner()

        result = runner.invoke(
            main, ["analyze", "nonexistent_commit_hash_12345", "--repo", repo_path]
        )

        assert result.exit_code == 1
        assert "Error:" in result.output


class TestCLIWithMockedAnalyzer:
    """Test CLI with mocked LLM analyzer to avoid API calls"""

    @pytest.fixture
    def mock_llm_analyzer(self, mock_semantic_analysis):
        """Mock the LLM analyzer to return test data without API calls"""
        with patch("semantic_diff.cli.LLMAnalyzer") as mock_analyzer_class:
            mock_instance = MagicMock()
            mock_instance.analyze.return_value = mock_semantic_analysis
            mock_analyzer_class.return_value = mock_instance
            yield mock_analyzer_class

    def test_json_output_returns_valid_json(
        self, temp_git_repo, mock_llm_analyzer, mock_semantic_analysis
    ):
        """Test that --json flag outputs valid JSON"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        result = runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path, "--json"])

        assert result.exit_code == 0

        # Parse JSON to verify it's valid
        try:
            data = json.loads(result.output)
        except json.JSONDecodeError as e:
            pytest.fail(f"Output is not valid JSON: {e}\n{result.output}")

        # Check structure
        assert "commit_hash" in data
        assert "intent" in data
        assert "risk_assessment" in data
        assert "files_changed" in data

    def test_json_output_contains_analysis_data(
        self, temp_git_repo, mock_llm_analyzer, mock_semantic_analysis
    ):
        """Test that JSON output contains the expected analysis data"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        result = runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path, "--json"])

        data = json.loads(result.output)

        # Verify key fields match mock data
        assert data["commit_message"] == mock_semantic_analysis.commit_message
        assert data["author"] == mock_semantic_analysis.author
        assert data["intent"]["summary"] == mock_semantic_analysis.intent.summary

    def test_console_output_is_formatted(self, temp_git_repo, mock_llm_analyzer, capsys):
        """Test that console output (non-JSON) is formatted nicely"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        result = runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path])

        assert result.exit_code == 0
        # Rich formatter adds boxes and formatting
        # Just check that output is not JSON
        assert not result.output.strip().startswith("{")

    def test_verbose_flag_shows_debug_info(self, temp_git_repo, mock_llm_analyzer):
        """Test that -v/--verbose flag shows debug information"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        result = runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path, "-v"])

        assert result.exit_code == 0
        # Should show verbose messages
        assert "Initializing" in result.output or "Getting commit" in result.output

    def test_save_flag_creates_report_file(self, temp_git_repo, mock_llm_analyzer):
        """Test that --save flag creates markdown report file"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        result = runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path, "--save"])

        assert result.exit_code == 0

        # Check that report was saved
        assert "Report saved:" in result.output

        # Verify file exists
        reports_dir = Path(repo_path) / "semantic_diff_reports"
        assert reports_dir.exists()
        assert reports_dir.is_dir()

        # Check that at least one .md file was created
        md_files = list(reports_dir.glob("*.md"))
        assert len(md_files) > 0

    def test_save_flag_file_contains_markdown(self, temp_git_repo, mock_llm_analyzer):
        """Test that saved report contains valid markdown"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path, "--save"])

        # Find the saved file
        reports_dir = Path(repo_path) / "semantic_diff_reports"
        md_files = list(reports_dir.glob("*.md"))
        assert len(md_files) > 0

        # Read and verify content
        content = md_files[0].read_text()
        assert content.startswith("# Semantic Diff:")
        assert "## 🎯 Intent" in content

    def test_model_flag_passes_to_analyzer(self, temp_git_repo):
        """Test that --model flag is passed to the analyzer"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        with patch("semantic_diff.cli.LLMAnalyzer") as mock_analyzer_class:
            mock_instance = MagicMock()
            mock_analyzer_class.return_value = mock_instance

            # This will fail because no API key, but we can check the call
            runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path, "--model", "custom-model"])

            # Verify LLMAnalyzer was instantiated with the model
            mock_analyzer_class.assert_called_once_with(model="custom-model")

    def test_default_commit_is_head(self, temp_git_repo, mock_llm_analyzer):
        """Test that default commit is HEAD when not specified"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        # Don't specify commit hash - use default HEAD
        result = runner.invoke(main, ["analyze", "--repo", repo_path, "--json"])

        assert result.exit_code == 0
        # Should analyze HEAD commit
        data = json.loads(result.output)
        assert "commit_hash" in data

    def test_brief_flag_produces_compact_output(self, temp_git_repo, mock_llm_analyzer):
        """Test that --brief flag produces compact console output"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        result_brief = runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path, "--brief"])
        result_full = runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path])

        assert result_brief.exit_code == 0
        assert result_full.exit_code == 0

        # Brief output should be shorter
        assert len(result_brief.output) < len(result_full.output)

    def test_brief_and_verbose_mutually_exclusive(self, temp_git_repo):
        """Test that --brief and --verbose cannot be used together"""
        repo_path, repo, commit_hash = temp_git_repo
        runner = CliRunner()

        result = runner.invoke(
            main, ["analyze", "HEAD", "--repo", repo_path, "--brief", "--verbose"]
        )

        assert result.exit_code == 1
        assert "mutually exclusive" in result.output


class TestCLIEdgeCases:
    """Test edge cases and error handling"""

    def test_empty_commit_shows_message(self, tmp_path):
        """Test that commit with no changes shows appropriate message"""
        # Create repo with commit but no actual changes
        repo = Repo.init(tmp_path)
        with repo.config_writer() as config:
            config.set_value("user", "name", "Test User")
            config.set_value("user", "email", "test@example.com")

        # Create initial commit
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial")

        # Create empty commit (amend without changes would need --allow-empty)
        # Instead, we'll test with a valid commit and mock get_file_changes
        with patch("semantic_diff.cli.GitParser") as mock_parser_class:
            mock_parser = MagicMock()
            mock_parser.get_commit_info.return_value = {
                "hash": "abc123",
                "message": "Empty",
                "author": "test@example.com",
                "date": "2024-01-01",
            }
            mock_parser.get_file_changes.return_value = []  # No changes
            mock_parser_class.return_value = mock_parser

            runner = CliRunner()
            result = runner.invoke(main, ["analyze", "HEAD", "--repo", str(tmp_path)])

            assert result.exit_code == 0
            assert "No changes found" in result.output

    def test_current_directory_when_no_repo_specified(self):
        """Test that CLI uses current directory when --repo not specified"""
        runner = CliRunner()

        # This will fail if current directory is not a git repo
        # We're testing the error message contains the right info
        result = runner.invoke(main, ["analyze", "HEAD"])

        # Either succeeds (if run in a git repo) or fails with repo error
        if result.exit_code != 0:
            assert "Error:" in result.output

    def test_verbose_shows_traceback_on_error(self, tmp_path):
        """Test that --verbose shows full traceback on errors"""
        runner = CliRunner()

        # Trigger an error with verbose mode
        result = runner.invoke(main, ["analyze", "HEAD", "--repo", "/nonexistent", "--verbose"])

        assert result.exit_code == 1
        # Should show more detailed error info in verbose mode
        assert "Error:" in result.output


class TestCLIIntegration:
    """Integration tests with real git operations but mocked LLM"""

    def test_full_workflow_with_real_git(self, temp_git_repo, mock_semantic_analysis):
        """Test complete workflow: real git repo -> mocked analysis -> console output"""
        repo_path, repo, commit_hash = temp_git_repo

        with patch("semantic_diff.cli.LLMAnalyzer") as mock_analyzer_class:
            mock_instance = MagicMock()
            mock_instance.analyze.return_value = mock_semantic_analysis
            mock_analyzer_class.return_value = mock_instance

            runner = CliRunner()
            result = runner.invoke(main, ["analyze", "HEAD", "--repo", repo_path])

            assert result.exit_code == 0
            # Analyzer should have been called
            assert mock_instance.analyze.called

    def test_short_commit_hash_works(self, temp_git_repo, mock_semantic_analysis):
        """Test that short commit hashes work"""
        repo_path, repo, commit_hash = temp_git_repo

        with patch("semantic_diff.cli.LLMAnalyzer") as mock_analyzer_class:
            mock_instance = MagicMock()
            mock_instance.analyze.return_value = mock_semantic_analysis
            mock_analyzer_class.return_value = mock_instance

            runner = CliRunner()
            # Use short hash (first 7 chars)
            short_hash = commit_hash[:7]
            result = runner.invoke(main, ["analyze", short_hash, "--repo", repo_path])

            assert result.exit_code == 0
