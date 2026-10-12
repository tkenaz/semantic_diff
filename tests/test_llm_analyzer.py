"""
Tests for LLMAnalyzer - Claude-based semantic analyzer
"""

import pytest

from semantic_diff.analyzers.llm_analyzer import LLMAnalyzer
from semantic_diff.models import FileChange, RiskLevel
from semantic_diff.providers import Completion


class ScriptedProvider:
    """Fake LLMProvider: returns a scripted completion and records calls."""

    model = "scripted-model"

    def __init__(self, completion: Completion | None = None):
        self.completion = completion or Completion(text="{}", input_tokens=0, output_tokens=0)
        self.calls = []

    def complete(self, prompt, *, max_tokens):
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens})
        return self.completion


class TestFormatFilesSummary:
    """Test _format_files_summary method"""

    @pytest.fixture
    def analyzer(self):
        return LLMAnalyzer(ScriptedProvider())

    def test_format_single_file(self, analyzer):
        """Test formatting single file"""
        files = [
            FileChange(
                path="main.py", change_type="modified", additions=10, deletions=5, language="python"
            )
        ]
        result = analyzer._format_files_summary(files)
        assert "main.py" in result
        assert "modified" in result
        assert "+10/-5" in result
        assert "[python]" in result

    def test_format_multiple_files(self, analyzer):
        """Test formatting multiple files"""
        files = [
            FileChange(
                path="a.py", change_type="added", additions=100, deletions=0, language="python"
            ),
            FileChange(
                path="b.js", change_type="deleted", additions=0, deletions=50, language="javascript"
            ),
            FileChange(
                path="c.txt", change_type="modified", additions=5, deletions=3, language=None
            ),
        ]
        result = analyzer._format_files_summary(files)
        assert "a.py" in result
        assert "b.js" in result
        assert "c.txt" in result
        assert "[python]" in result
        assert "[javascript]" in result

    def test_format_file_without_language(self, analyzer):
        """Test formatting file without detected language"""
        files = [
            FileChange(
                path="Makefile", change_type="modified", additions=1, deletions=1, language=None
            )
        ]
        result = analyzer._format_files_summary(files)
        assert "Makefile" in result
        assert "[" not in result or "[]" not in result  # No language tag


class TestFormatDiffs:
    """Test _format_diffs method"""

    @pytest.fixture
    def analyzer(self):
        return LLMAnalyzer(ScriptedProvider())

    def test_format_single_diff(self, analyzer):
        """Test formatting single diff"""
        files = [
            FileChange(
                path="test.py",
                change_type="modified",
                diff_content="+new line\n-old line",
                language="python",
            )
        ]
        result = analyzer._format_diffs(files)
        assert "test.py" in result
        assert "+new line" in result
        assert "-old line" in result
        assert "```python" in result

    def test_format_diffs_truncation(self, analyzer):
        """Test that long diffs are truncated"""
        long_content = "x" * 20000  # Exceeds max_total_chars
        files = [
            FileChange(
                path="huge.py", change_type="modified", diff_content=long_content, language="python"
            )
        ]
        result = analyzer._format_diffs(files, max_total_chars=1000)
        assert len(result) < len(long_content)
        assert "(truncated)" in result

    def test_format_many_files_truncation(self, analyzer):
        """Test that many files are truncated"""
        files = [
            FileChange(
                path=f"file{i}.py",
                change_type="modified",
                diff_content="content " * 500,
                language="python",
            )
            for i in range(20)
        ]
        result = analyzer._format_diffs(files, max_total_chars=5000)
        assert "truncated" in result.lower()
        assert "more files" in result.lower()


class TestFormatProjectContext:
    """Test _format_project_context method"""

    @pytest.fixture
    def analyzer(self):
        return LLMAnalyzer(ScriptedProvider())

    def test_format_full_context(self, analyzer):
        """Test formatting full project context"""
        context = {
            "languages": ["python", "javascript"],
            "package_manager": "pip",
            "has_tests": True,
            "has_ci": True,
            "root_files": ["README.md", "setup.py"],
            "directories": ["src", "tests"],
        }
        result = analyzer._format_project_context(context)
        assert "python" in result
        assert "javascript" in result
        assert "pip" in result
        assert "Yes" in result  # has_tests
        assert "README.md" in result

    def test_format_empty_context(self, analyzer):
        """Test formatting empty/minimal context"""
        context = {}
        result = analyzer._format_project_context(context)
        assert "unknown" in result.lower()


class TestParseResponse:
    """Test _parse_response method"""

    @pytest.fixture
    def analyzer(self):
        return LLMAnalyzer(ScriptedProvider())

    def test_parse_json_in_code_block(self, analyzer):
        """Test parsing JSON in ```json block"""
        response = """Here's my analysis:
```json
{"intent": {"summary": "test"}}
```
Done."""
        result = analyzer._parse_response(response)
        assert result["intent"]["summary"] == "test"

    def test_parse_json_in_plain_code_block(self, analyzer):
        """Test parsing JSON in plain ``` block"""
        response = """Analysis:
```
{"intent": {"summary": "plain"}}
```"""
        result = analyzer._parse_response(response)
        assert result["intent"]["summary"] == "plain"

    def test_parse_raw_json(self, analyzer):
        """Test parsing raw JSON without code blocks"""
        response = '{"intent": {"summary": "raw"}}'
        result = analyzer._parse_response(response)
        assert result["intent"]["summary"] == "raw"

    def test_parse_invalid_json(self, analyzer):
        """Test parsing invalid JSON raises ValueError"""
        response = "This is not JSON at all"
        with pytest.raises(ValueError, match="Failed to parse"):
            analyzer._parse_response(response)

    def test_parse_malformed_json(self, analyzer):
        """Test parsing malformed JSON raises ValueError"""
        response = '{"intent": {"summary": missing_quotes}}'
        with pytest.raises(ValueError, match="Failed to parse"):
            analyzer._parse_response(response)


class TestValidateResponseData:
    """Test _validate_response_data method"""

    @pytest.fixture
    def analyzer(self):
        return LLMAnalyzer(ScriptedProvider())

    def test_validate_empty_data(self, analyzer):
        """Test validation fills defaults for empty data"""
        data = {}
        result = analyzer._validate_response_data(data)

        assert "intent" in result
        assert result["intent"]["summary"] == "Unable to determine intent"
        assert result["intent"]["confidence"] <= 0.3  # Lowered due to missing fields

        assert "impact_map" in result
        assert "risk_assessment" in result
        assert result["risk_assessment"]["overall_risk"] == "medium"
        assert "review_questions" in result

    def test_validate_partial_data(self, analyzer):
        """Test validation fills only missing fields"""
        data = {
            "intent": {
                "summary": "Custom summary",
                "reasoning": "Custom reasoning",
                "confidence": 0.9,
            }
        }
        result = analyzer._validate_response_data(data)

        assert result["intent"]["summary"] == "Custom summary"
        # Confidence is lowered to 0.3 when critical fields (risk_assessment) are missing
        assert result["intent"]["confidence"] == 0.3
        assert "impact_map" in result

    def test_validate_full_data(self, analyzer):
        """Test validation passes through complete data"""
        data = {
            "intent": {"summary": "Test", "reasoning": "Test", "confidence": 0.8},
            "impact_map": {"direct_impacts": [], "indirect_impacts": [], "affected_components": []},
            "risk_assessment": {
                "overall_risk": "low",
                "risks": [],
                "breaking_changes": False,
                "requires_migration": False,
            },
            "review_questions": [],
        }
        result = analyzer._validate_response_data(data)
        assert result["intent"]["confidence"] == 0.8
        assert result["risk_assessment"]["overall_risk"] == "low"


class TestAnalyze:
    """Test analyze method - full integration"""

    @pytest.fixture
    def analyzer(self):
        return LLMAnalyzer(ScriptedProvider())

    def test_analyze_returns_semantic_analysis(self, analyzer):
        """Test analyze returns properly structured SemanticAnalysis"""
        # Mock response
        analyzer.provider.completion = Completion(
            text="""```json
{
    "intent": {"summary": "Test change", "reasoning": "Testing", "confidence": 0.9},
    "impact_map": {"direct_impacts": [], "indirect_impacts": [], "affected_components": []},
    "risk_assessment": {"overall_risk": "low", "risks": [], "breaking_changes": false, "requires_migration": false},
    "review_questions": []
}
```""",
            input_tokens=100,
            output_tokens=50,
        )

        commit_info = {
            "hash": "abc123def456",
            "short_hash": "abc123de",
            "message": "Test commit",
            "author": "Test <test@test.com>",
            "date": "2024-01-01T00:00:00",
        }

        files = [
            FileChange(
                path="test.py",
                change_type="modified",
                additions=10,
                deletions=5,
                diff_content="+new\n-old",
                language="python",
            )
        ]

        project_context = {
            "languages": ["python"],
            "package_manager": "pip",
            "has_tests": True,
            "has_ci": False,
            "root_files": ["setup.py"],
            "directories": ["src"],
        }

        result = analyzer.analyze(commit_info, files, project_context)

        assert result.commit_hash == "abc123def456"
        assert result.intent.summary == "Test change"
        assert result.intent.confidence == 0.9
        assert result.risk_assessment.overall_risk == RiskLevel.LOW
        assert result.tokens_used == 150
        assert result.analysis_model == "scripted-model"
        assert analyzer.last_usage == {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }

    def test_analyze_sends_prompt_with_commit_and_diff(self, analyzer):
        analyzer.provider.completion = Completion(text="{}", input_tokens=1, output_tokens=1)
        commit_info = {
            "hash": "abc123def456",
            "short_hash": "abc123de",
            "message": "Tighten auth",
            "author": "Test <test@test.com>",
            "date": "2024-01-01T00:00:00",
        }
        files = [FileChange(path="auth.py", change_type="modified", diff_content="+strict = True")]

        analyzer.analyze(commit_info, files, {})

        (call,) = analyzer.provider.calls
        assert call["max_tokens"] == 4096
        assert "Tighten auth" in call["prompt"]
        assert "+strict = True" in call["prompt"]

    def test_analyze_with_empty_files(self, analyzer):
        """Test analyze with empty file list"""
        analyzer.provider.completion = Completion(
            text='{"intent": {"summary": "Empty", "reasoning": "No files", "confidence": 0.5}}',
            input_tokens=50,
            output_tokens=25,
        )

        commit_info = {
            "hash": "abc123",
            "short_hash": "abc123",
            "message": "Empty commit",
            "author": "Test",
            "date": "2024-01-01",
        }

        result = analyzer.analyze(commit_info, [], {})

        assert result is not None
        assert result.intent.summary == "Empty"
