"""
Tests for formatters - console and markdown output
"""

from semantic_diff.formatters.console_formatter import ConsoleFormatter
from semantic_diff.formatters.markdown_formatter import MarkdownFormatter
from semantic_diff.models import (
    DiffCoverage,
    FileChange,
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
        assert mock_semantic_analysis.change_set.ref in output
        assert mock_semantic_analysis.change_set.authors[0] in output

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
        malicious_analysis = mock_semantic_analysis.model_copy(deep=True)
        malicious_analysis.change_set.title = "<script>alert('xss')</script> Fix bug"

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
        assert saved_path.name.startswith(mock_semantic_analysis.change_set.head_sha[:8] + "_")
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


class TestMarkdownFormatterMergeRequest:
    def test_header_shows_range_title_and_authors(self, mock_mr_analysis):
        output = MarkdownFormatter().format(mock_mr_analysis)

        assert output.startswith("# Semantic Diff: 0123abcd..abc123de")
        assert "**Merge request:** `0123abcd..abc123de`" in output
        assert "**Authors:** Dev One &lt;d1@x&gt;, Dev Two &lt;d2@x&gt;" in output
        assert "> AHUB-1 Add JWT authentication" in output
        assert "**Commit:**" not in output

    def test_lists_commits_oldest_first(self, mock_mr_analysis):
        output = MarkdownFormatter().format(mock_mr_analysis)

        first = output.index("`11111111` feat: add jwt")
        second = output.index("`22222222` test: jwt expiry")
        assert "### Commits (2)" in output
        assert first < second

    def test_commit_subjects_are_escaped(self, mock_mr_analysis):
        analysis = mock_mr_analysis.model_copy(deep=True)
        analysis.change_set.commits[0].subject = "<img src=x onerror=alert(1)>"

        output = MarkdownFormatter().format(analysis)

        assert "<img" not in output

    def test_report_filename_is_prefixed(self, mock_mr_analysis, tmp_path):
        saved = MarkdownFormatter().save(mock_mr_analysis, tmp_path)

        assert saved.name.startswith("mr_abc123de_")

    def test_commit_report_has_no_commit_list(self, mock_semantic_analysis):
        output = MarkdownFormatter().format(mock_semantic_analysis)

        assert "### Commits" not in output


class TestConsoleFormatterMergeRequest:
    def test_full_header_shows_range_and_commit_count(self, mock_mr_analysis, capsys):
        ConsoleFormatter().format(mock_mr_analysis)

        output = capsys.readouterr().out
        assert "AHUB-1 Add JWT authentication" in output
        assert "0123abcd..abc123de" in output
        assert "2 commits" in output

    def test_title_is_not_interpreted_as_rich_markup(self, mock_mr_analysis, capsys):
        analysis = mock_mr_analysis.model_copy(deep=True)
        analysis.change_set.title = "[red]Totally safe[/red]"

        ConsoleFormatter().format(analysis)
        ConsoleFormatter(brief=True).format(analysis)

        assert capsys.readouterr().out.count("[red]Totally safe[/red]") == 2

    def test_brief_header_shows_commit_count(self, mock_mr_analysis, capsys):
        ConsoleFormatter(brief=True).format(mock_mr_analysis)

        output = capsys.readouterr().out
        assert "2 commits" in output


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
        assert mock_semantic_analysis.change_set.title in output
        assert mock_semantic_analysis.change_set.ref in output
        assert mock_semantic_analysis.change_set.authors[0] in output

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


class TestConsoleFormatterBriefMode:
    """Test ConsoleFormatter brief mode output"""

    def test_brief_mode_initialization(self):
        """Test that brief mode can be initialized"""
        formatter = ConsoleFormatter(brief=True)
        assert formatter.brief is True

        formatter_full = ConsoleFormatter(brief=False)
        assert formatter_full.brief is False

        formatter_default = ConsoleFormatter()
        assert formatter_default.brief is False

    def test_brief_mode_produces_shorter_output(self, mock_semantic_analysis, capsys):
        """Test that brief mode produces less output than full mode"""
        formatter_brief = ConsoleFormatter(brief=True)
        formatter_full = ConsoleFormatter(brief=False)

        formatter_brief.format(mock_semantic_analysis)
        brief_output = capsys.readouterr().out

        formatter_full.format(mock_semantic_analysis)
        full_output = capsys.readouterr().out

        # Brief should be significantly shorter
        assert len(brief_output) < len(full_output)

    def test_brief_mode_includes_essential_info(self, mock_semantic_analysis, capsys):
        """Test that brief mode includes essential information"""
        formatter = ConsoleFormatter(brief=True)
        formatter.format(mock_semantic_analysis)

        output = capsys.readouterr().out

        # Should include commit info
        assert mock_semantic_analysis.change_set.ref in output
        assert mock_semantic_analysis.change_set.title in output

        # Should include intent summary
        assert mock_semantic_analysis.intent.summary in output

        # Should include risk level
        assert "HIGH" in output or "Risk" in output

    def test_brief_mode_excludes_details(self, mock_semantic_analysis, capsys):
        """Test that brief mode excludes detailed reasoning"""
        formatter = ConsoleFormatter(brief=True)
        formatter.format(mock_semantic_analysis)

        output = capsys.readouterr().out

        # Should NOT include detailed reasoning
        assert mock_semantic_analysis.intent.reasoning not in output

        # Should NOT include "Files Changed" section header
        assert "Files Changed" not in output

        # Should NOT include impact map section
        assert "Impact Map" not in output

    def test_brief_mode_limits_questions(self, mock_semantic_analysis, capsys):
        """Test that brief mode limits questions but shows critical/high"""
        from semantic_diff.models import ReviewQuestion

        # Create analysis with many questions of different priorities
        analysis = mock_semantic_analysis.model_copy()
        analysis.review_questions = [
            ReviewQuestion(
                question="Low priority question 1?",
                context="context",
                priority=RiskLevel.LOW,
            ),
            ReviewQuestion(
                question="Critical question must show?",
                context="context",
                priority=RiskLevel.CRITICAL,
            ),
            ReviewQuestion(
                question="High priority question?",
                context="context",
                priority=RiskLevel.HIGH,
            ),
            ReviewQuestion(
                question="Medium question 1?",
                context="context",
                priority=RiskLevel.MEDIUM,
            ),
            ReviewQuestion(
                question="Low priority question 2?",
                context="context",
                priority=RiskLevel.LOW,
            ),
        ]

        formatter = ConsoleFormatter(brief=True)
        formatter.format(analysis)

        output = capsys.readouterr().out

        # CRITICAL and HIGH must always be shown
        assert "Critical question must show?" in output
        assert "High priority question?" in output

        # Should show "and X more" for hidden questions
        assert "more" in output

    def test_brief_mode_shows_all_critical_high_even_if_many(self, mock_semantic_analysis, capsys):
        """Test that ALL critical/high questions are shown even if >3"""
        from semantic_diff.models import ReviewQuestion

        analysis = mock_semantic_analysis.model_copy()
        analysis.review_questions = [
            ReviewQuestion(question="Critical 1?", context="c", priority=RiskLevel.CRITICAL),
            ReviewQuestion(question="Critical 2?", context="c", priority=RiskLevel.CRITICAL),
            ReviewQuestion(question="High 1?", context="c", priority=RiskLevel.HIGH),
            ReviewQuestion(question="High 2?", context="c", priority=RiskLevel.HIGH),
            ReviewQuestion(question="Medium 1?", context="c", priority=RiskLevel.MEDIUM),
        ]

        formatter = ConsoleFormatter(brief=True)
        formatter.format(analysis)

        output = capsys.readouterr().out

        # All 4 critical/high should be shown
        assert "Critical 1?" in output
        assert "Critical 2?" in output
        assert "High 1?" in output
        assert "High 2?" in output

    def test_brief_mode_minimal_analysis(self, mock_minimal_analysis, capsys):
        """Test brief mode with minimal data"""
        formatter = ConsoleFormatter(brief=True)
        formatter.format(mock_minimal_analysis)

        output = capsys.readouterr().out

        # Should not crash and should show basic info
        assert len(output) > 0
        assert "LOW" in output


PARTIAL = DiffCoverage(
    budget_tokens=60_000,
    shown_lines=870,
    total_lines=1000,
    trimmed=["src/core.py"],
    omitted=["src/big_*.py", "src/huge.py"],
    noise=["pnpm-lock.yaml"],
)


class TestDiffCoverageInReports:
    def test_markdown_states_coverage_and_every_gap(self, mock_mr_analysis):
        analysis = mock_mr_analysis.model_copy(update={"diff_coverage": PARTIAL})

        report = MarkdownFormatter().format(analysis)

        assert "**Diff coverage:** 87% of changed lines (budget 60,000 tokens)" in report
        assert "- Trimmed to whole hunks: src/core.py" in report
        assert "- Not shown (over budget): src/big\\_\\*.py, src/huge.py" in report
        assert "pnpm-lock.yaml\n\n## 📁 Files Changed" in report
        assert "- Skipped (lock/generated/binary): pnpm-lock.yaml" in report

    def test_markdown_full_coverage_has_no_gap_lines(self, mock_mr_analysis):
        full = DiffCoverage(budget_tokens=60_000, shown_lines=5, total_lines=5)
        analysis = mock_mr_analysis.model_copy(update={"diff_coverage": full})

        report = MarkdownFormatter().format(analysis)

        assert "**Diff coverage:** 100% of changed lines" in report
        assert "Not shown" not in report
        assert "Trimmed" not in report

    def test_markdown_without_coverage_says_nothing_about_it(self, mock_mr_analysis):
        assert "Diff coverage" not in MarkdownFormatter().format(mock_mr_analysis)

    def test_console_shows_coverage_in_both_modes(self, mock_mr_analysis, capsys):
        analysis = mock_mr_analysis.model_copy(update={"diff_coverage": PARTIAL})

        ConsoleFormatter().format(analysis)
        ConsoleFormatter(brief=True).format(analysis)

        output = capsys.readouterr().out
        assert output.count(" • diff 87%") == 2

    def test_console_warns_when_files_were_not_seen(self, mock_mr_analysis, capsys):
        analysis = mock_mr_analysis.model_copy(update={"diff_coverage": PARTIAL})

        ConsoleFormatter().format(analysis)

        output = " ".join(capsys.readouterr().out.split())
        assert "2 files not shown to the model" in output
        assert "src/big_*.py, src/huge.py" in output

    def test_console_warning_singular(self, mock_mr_analysis, capsys):
        one = PARTIAL.model_copy(update={"omitted": ["src/huge.py"]})
        analysis = mock_mr_analysis.model_copy(update={"diff_coverage": one})

        ConsoleFormatter().format(analysis)

        assert "1 file not shown to the model" in capsys.readouterr().out

    def test_console_without_coverage_omits_it(self, mock_mr_analysis, capsys):
        ConsoleFormatter().format(mock_mr_analysis)

        output = capsys.readouterr().out
        assert "diff " not in output
        assert "not shown" not in output
