"""
Tests for formatters - console and markdown output
"""
import re
from pathlib import Path
import pytest

from semantic_diff.formatters.console_formatter import ConsoleFormatter
from semantic_diff.formatters.markdown_formatter import MarkdownFormatter
from semantic_diff.models import (
    SemanticAnalysis,
    FileChange,
    Intent,
    ImpactMap,
    RiskAssessment,
    RiskLevel,
)


class TestMarkdownFormatter:
    """Test MarkdownFormatter output generation"""

    def test_format_generates_valid_markdown(self, mock_semantic_analysis):
        """Test that format() generates valid markdown structure"""
        formatter = MarkdownFormatter()
        output = formatter.format(mock_semantic_analysis)

        # Check basic markdown structure
        assert output.startswith("# Semantic Diff:")
        assert "## 📁 Files Changed" in output
        assert "## 🎯 Intent" in output
        assert "## 🗺️ Impact Map" in output
        assert "## ⚠️ Risk Assessment" in output
        assert "## ❓ Review Questions" in output

        # Check commit info is present
        assert mock_semantic_analysis.commit_hash[:8] in output
        assert mock_semantic_analysis.author in output

        # Check table structure for files
        assert "| File | Change | + | - | Lang |" in output
        assert "|------|--------|---|---|------|" in output

    def test_format_includes_all_analysis_data(self, mock_semantic_analysis):
        """Test that all analysis fields are included in output"""
        formatter = MarkdownFormatter()
        output = formatter.format(mock_semantic_analysis)

        # Intent
        assert mock_semantic_analysis.intent.summary in output
        assert mock_semantic_analysis.intent.reasoning in output
        assert "92%" in output  # confidence

        # Files
        assert "src/main.py" in output
        assert "src/auth.py" in output

        # Risk assessment
        assert "HIGH" in output  # overall risk
        assert "BREAKING CHANGES DETECTED" in output

        # Review questions
        assert "How are existing active sessions handled" in output
        assert "Is there rate limiting" in output

        # Metadata
        assert "claude-sonnet-4-5-20250929" in output
        assert "5,423 tokens" in output

    def test_format_minimal_analysis(self, mock_minimal_analysis):
        """Test format with minimal data (no risks, no questions)"""
        formatter = MarkdownFormatter()
        output = formatter.format(mock_minimal_analysis)

        # Should still have basic structure
        assert "# Semantic Diff:" in output
        assert "## 📁 Files Changed" in output
        assert "## 🎯 Intent" in output
        assert "## ⚠️ Risk Assessment" in output

        # Should handle empty sections gracefully
        assert "LOW" in output  # overall risk
        assert "BREAKING CHANGES" not in output
        assert "## ❓ Review Questions" not in output  # no questions section

    def test_escape_md_prevents_html_injection(self):
        """Test that _escape_md properly escapes HTML and markdown"""
        formatter = MarkdownFormatter()

        # Test HTML escaping
        assert "&lt;script&gt;" in formatter._escape_md("<script>")
        assert "&lt;img src=x&gt;" in formatter._escape_md("<img src=x>")

        # Test markdown special chars
        malicious = "<script>alert('xss')</script>"
        escaped = formatter._escape_md(malicious)
        assert "<script>" not in escaped
        assert "&lt;" in escaped or "\\<" in escaped

    def test_escape_md_handles_commit_message_injection(self, mock_semantic_analysis):
        """Test that malicious commit messages are escaped"""
        formatter = MarkdownFormatter()

        # Create analysis with malicious commit message
        malicious_analysis = mock_semantic_analysis.model_copy()
        malicious_analysis.commit_message = "<script>alert('xss')</script> Fix bug"

        output = formatter.format(malicious_analysis)

        # Should not contain raw HTML
        assert "<script>" not in output
        # Should escape the tags (html.escape converts < to &lt;)
        assert "&lt;script&gt;" in output

    def test_escape_md_handles_file_path_injection(self, mock_semantic_analysis):
        """Test that malicious file paths are escaped"""
        formatter = MarkdownFormatter()

        # Create analysis with malicious file path
        malicious_analysis = mock_semantic_analysis.model_copy()
        malicious_analysis.files_changed[0].path = "../../../etc/passwd`rm -rf /`"

        output = formatter.format(malicious_analysis)

        # Backticks should be escaped
        assert "\\`" in output or "`" not in output.split("```")[0]

    def test_escape_inline_code_escapes_backticks(self):
        """Test that _escape_inline_code escapes backticks"""
        formatter = MarkdownFormatter()

        # Test backtick escaping
        assert formatter._escape_inline_code("test`code") == "test\\`code"
        assert formatter._escape_inline_code("``double``") == "\\`\\`double\\`\\`"

        # Test empty/None handling
        assert formatter._escape_inline_code("") == ""
        assert formatter._escape_inline_code(None) == ""

    def test_save_creates_file_in_correct_location(self, mock_semantic_analysis, tmp_path):
        """Test that save() creates file in the correct directory"""
        formatter = MarkdownFormatter()
        reports_dir = tmp_path / "semantic_diff_reports"

        saved_path = formatter.save(mock_semantic_analysis, reports_dir)

        # Check directory was created
        assert reports_dir.exists()
        assert reports_dir.is_dir()

        # Check file was created
        assert saved_path.exists()
        assert saved_path.is_file()

        # Check filename format: <short_hash>_<timestamp>.md
        assert saved_path.name.startswith(mock_semantic_analysis.commit_hash[:8])
        assert saved_path.name.endswith(".md")

    def test_save_file_contains_formatted_content(self, mock_semantic_analysis, tmp_path):
        """Test that saved file contains the formatted markdown"""
        formatter = MarkdownFormatter()
        reports_dir = tmp_path / "reports"

        saved_path = formatter.save(mock_semantic_analysis, reports_dir)

        # Read saved content
        content = saved_path.read_text(encoding="utf-8")

        # Should match format() output
        expected_content = formatter.format(mock_semantic_analysis)
        assert content == expected_content

        # Verify key content is present
        assert "# Semantic Diff:" in content
        assert mock_semantic_analysis.intent.summary in content

    def test_save_creates_unique_filenames(self, mock_semantic_analysis, tmp_path):
        """Test that multiple saves create unique files"""
        import time

        formatter = MarkdownFormatter()
        reports_dir = tmp_path / "reports"

        # Save twice with delay to ensure different timestamps
        path1 = formatter.save(mock_semantic_analysis, reports_dir)
        time.sleep(1)  # Ensure different second in timestamp
        path2 = formatter.save(mock_semantic_analysis, reports_dir)

        # Should create different files (different timestamps)
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

    def test_risk_icon_mapping(self):
        """Test that risk levels map to correct icons"""
        formatter = MarkdownFormatter()

        assert formatter._risk_icon(RiskLevel.LOW) == "✓"
        assert formatter._risk_icon(RiskLevel.MEDIUM) == "⚠️"
        assert formatter._risk_icon(RiskLevel.HIGH) == "⚡"
        assert formatter._risk_icon(RiskLevel.CRITICAL) == "🔥"


class TestConsoleFormatter:
    """Test ConsoleFormatter terminal output"""

    def test_format_does_not_crash_on_valid_input(self, mock_semantic_analysis, capsys):
        """Test that format() runs without errors on valid input"""
        formatter = ConsoleFormatter()

        # Should not raise exception
        formatter.format(mock_semantic_analysis)

        # Check that something was printed
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_format_includes_commit_info(self, mock_semantic_analysis, capsys):
        """Test that console output includes commit information"""
        formatter = ConsoleFormatter()
        formatter.format(mock_semantic_analysis)

        captured = capsys.readouterr()
        output = captured.out

        # Check commit info is present
        assert mock_semantic_analysis.commit_message in output
        assert mock_semantic_analysis.commit_hash[:8] in output
        assert mock_semantic_analysis.author in output

    def test_format_includes_analysis_sections(self, mock_semantic_analysis, capsys):
        """Test that all major analysis sections are included"""
        formatter = ConsoleFormatter()
        formatter.format(mock_semantic_analysis)

        captured = capsys.readouterr()
        output = captured.out

        # Check section headers (emoji may vary in output)
        assert "Intent" in output
        assert "Impact Map" in output
        assert "Risk Assessment" in output
        assert "Review Questions" in output

        # Check key content
        assert mock_semantic_analysis.intent.summary in output
        assert "HIGH" in output  # risk level

    def test_format_minimal_analysis(self, mock_minimal_analysis, capsys):
        """Test format with minimal analysis data"""
        formatter = ConsoleFormatter()
        formatter.format(mock_minimal_analysis)

        captured = capsys.readouterr()
        output = captured.out

        # Should still output basic info without crashing
        assert len(output) > 0
        assert "LOW" in output  # minimal risk

    def test_format_handles_long_file_list(self, mock_semantic_analysis, capsys):
        """Test that long file lists are truncated appropriately"""
        formatter = ConsoleFormatter()

        # Add many files
        many_files = mock_semantic_analysis.model_copy()
        for i in range(15):
            many_files.files_changed.append(
                FileChange(
                    path=f"src/file_{i}.py",
                    change_type="modified",
                    additions=i,
                    deletions=i,
                    language="python",
                )
            )

        formatter.format(many_files)

        captured = capsys.readouterr()
        output = captured.out

        # Should truncate and show "and X more"
        assert "and" in output and "more" in output

    def test_risk_icon_mapping(self):
        """Test that risk levels map to correct icons"""
        formatter = ConsoleFormatter()

        assert formatter._risk_icon(RiskLevel.LOW) == "✓"
        assert formatter._risk_icon(RiskLevel.MEDIUM) == "⚠"
        assert formatter._risk_icon(RiskLevel.HIGH) == "⚡"
        assert formatter._risk_icon(RiskLevel.CRITICAL) == "🔥"

    def test_risk_style_mapping(self):
        """Test that risk levels map to correct colors"""
        formatter = ConsoleFormatter()

        assert formatter._risk_style(RiskLevel.LOW) == "green"
        assert formatter._risk_style(RiskLevel.MEDIUM) == "yellow"
        assert formatter._risk_style(RiskLevel.HIGH) == "red"
        assert formatter._risk_style(RiskLevel.CRITICAL) == "bold red"

    def test_confidence_bar_rendering(self, mock_semantic_analysis, capsys):
        """Test that confidence bar is rendered correctly"""
        formatter = ConsoleFormatter()

        # Create analysis with specific confidence
        analysis = mock_semantic_analysis.model_copy()
        analysis.intent.confidence = 0.75  # 75%

        formatter.format(analysis)

        captured = capsys.readouterr()
        # Should show confidence percentage
        assert "75%" in captured.out or "0.75" in captured.out
