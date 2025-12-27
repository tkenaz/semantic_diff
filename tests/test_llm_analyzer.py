"""
Tests for LLMAnalyzer - Claude-based semantic analyzer
"""
import os
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

import anthropic

from semantic_diff.analyzers.llm_analyzer import LLMAnalyzer
from semantic_diff.models import FileChange, RiskLevel


class TestLLMAnalyzerInit:
    """Test LLMAnalyzer initialization"""
    
    def test_init_without_api_key(self):
        """Test initialization without API key raises ValueError"""
        with patch.dict(os.environ, {}, clear=True):
            with patch('semantic_diff.analyzers.llm_analyzer.load_dotenv'):
                with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not found"):
                    LLMAnalyzer()
    
    def test_init_with_api_key_from_env(self):
        """Test initialization with API key from environment"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic'):
                analyzer = LLMAnalyzer()
                assert analyzer.api_key == 'test-key'
    
    def test_init_with_custom_model(self):
        """Test initialization with custom model"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic'):
                analyzer = LLMAnalyzer(model='claude-3-opus')
                assert analyzer.model == 'claude-3-opus'
    
    def test_init_with_model_from_env(self):
        """Test initialization with model from environment"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SEMANTIC_DIFF_MODEL': 'claude-3-haiku'
        }):
            with patch('anthropic.Anthropic'):
                analyzer = LLMAnalyzer()
                assert analyzer.model == 'claude-3-haiku'


class TestFormatFilesSummary:
    """Test _format_files_summary method"""
    
    @pytest.fixture
    def analyzer(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic'):
                return LLMAnalyzer()
    
    def test_format_single_file(self, analyzer):
        """Test formatting single file"""
        files = [FileChange(
            path='main.py',
            change_type='modified',
            additions=10,
            deletions=5,
            language='python'
        )]
        result = analyzer._format_files_summary(files)
        assert 'main.py' in result
        assert 'modified' in result
        assert '+10/-5' in result
        assert '[python]' in result
    
    def test_format_multiple_files(self, analyzer):
        """Test formatting multiple files"""
        files = [
            FileChange(path='a.py', change_type='added', additions=100, deletions=0, language='python'),
            FileChange(path='b.js', change_type='deleted', additions=0, deletions=50, language='javascript'),
            FileChange(path='c.txt', change_type='modified', additions=5, deletions=3, language=None),
        ]
        result = analyzer._format_files_summary(files)
        assert 'a.py' in result
        assert 'b.js' in result
        assert 'c.txt' in result
        assert '[python]' in result
        assert '[javascript]' in result
    
    def test_format_file_without_language(self, analyzer):
        """Test formatting file without detected language"""
        files = [FileChange(
            path='Makefile',
            change_type='modified',
            additions=1,
            deletions=1,
            language=None
        )]
        result = analyzer._format_files_summary(files)
        assert 'Makefile' in result
        assert '[' not in result or '[]' not in result  # No language tag


class TestFormatDiffs:
    """Test _format_diffs method"""
    
    @pytest.fixture
    def analyzer(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic'):
                return LLMAnalyzer()
    
    def test_format_single_diff(self, analyzer):
        """Test formatting single diff"""
        files = [FileChange(
            path='test.py',
            change_type='modified',
            diff_content='+new line\n-old line',
            language='python'
        )]
        result = analyzer._format_diffs(files)
        assert 'test.py' in result
        assert '+new line' in result
        assert '-old line' in result
        assert '```python' in result
    
    def test_format_diffs_truncation(self, analyzer):
        """Test that long diffs are truncated"""
        long_content = 'x' * 20000  # Exceeds max_total_chars
        files = [FileChange(
            path='huge.py',
            change_type='modified',
            diff_content=long_content,
            language='python'
        )]
        result = analyzer._format_diffs(files, max_total_chars=1000)
        assert len(result) < len(long_content)
        assert '(truncated)' in result
    
    def test_format_many_files_truncation(self, analyzer):
        """Test that many files are truncated"""
        files = [
            FileChange(
                path=f'file{i}.py',
                change_type='modified',
                diff_content='content ' * 500,
                language='python'
            )
            for i in range(20)
        ]
        result = analyzer._format_diffs(files, max_total_chars=5000)
        assert 'truncated' in result.lower()
        assert 'more files' in result.lower()


class TestFormatProjectContext:
    """Test _format_project_context method"""
    
    @pytest.fixture
    def analyzer(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic'):
                return LLMAnalyzer()
    
    def test_format_full_context(self, analyzer):
        """Test formatting full project context"""
        context = {
            'languages': ['python', 'javascript'],
            'package_manager': 'pip',
            'has_tests': True,
            'has_ci': True,
            'root_files': ['README.md', 'setup.py'],
            'directories': ['src', 'tests'],
        }
        result = analyzer._format_project_context(context)
        assert 'python' in result
        assert 'javascript' in result
        assert 'pip' in result
        assert 'Yes' in result  # has_tests
        assert 'README.md' in result
    
    def test_format_empty_context(self, analyzer):
        """Test formatting empty/minimal context"""
        context = {}
        result = analyzer._format_project_context(context)
        assert 'unknown' in result.lower()


class TestParseResponse:
    """Test _parse_response method"""
    
    @pytest.fixture
    def analyzer(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic'):
                return LLMAnalyzer()
    
    def test_parse_json_in_code_block(self, analyzer):
        """Test parsing JSON in ```json block"""
        response = '''Here's my analysis:
```json
{"intent": {"summary": "test"}}
```
Done.'''
        result = analyzer._parse_response(response)
        assert result['intent']['summary'] == 'test'
    
    def test_parse_json_in_plain_code_block(self, analyzer):
        """Test parsing JSON in plain ``` block"""
        response = '''Analysis:
```
{"intent": {"summary": "plain"}}
```'''
        result = analyzer._parse_response(response)
        assert result['intent']['summary'] == 'plain'
    
    def test_parse_raw_json(self, analyzer):
        """Test parsing raw JSON without code blocks"""
        response = '{"intent": {"summary": "raw"}}'
        result = analyzer._parse_response(response)
        assert result['intent']['summary'] == 'raw'
    
    def test_parse_invalid_json(self, analyzer):
        """Test parsing invalid JSON raises ValueError"""
        response = 'This is not JSON at all'
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
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic'):
                return LLMAnalyzer()
    
    def test_validate_empty_data(self, analyzer):
        """Test validation fills defaults for empty data"""
        data = {}
        result = analyzer._validate_response_data(data)
        
        assert 'intent' in result
        assert result['intent']['summary'] == 'Unable to determine intent'
        assert result['intent']['confidence'] <= 0.3  # Lowered due to missing fields
        
        assert 'impact_map' in result
        assert 'risk_assessment' in result
        assert result['risk_assessment']['overall_risk'] == 'medium'
        assert 'review_questions' in result
    
    def test_validate_partial_data(self, analyzer):
        """Test validation fills only missing fields"""
        data = {
            'intent': {
                'summary': 'Custom summary',
                'reasoning': 'Custom reasoning',
                'confidence': 0.9
            }
        }
        result = analyzer._validate_response_data(data)
        
        assert result['intent']['summary'] == 'Custom summary'
        assert result['intent']['confidence'] == 0.9  # Not lowered
        assert 'impact_map' in result
    
    def test_validate_full_data(self, analyzer):
        """Test validation passes through complete data"""
        data = {
            'intent': {'summary': 'Test', 'reasoning': 'Test', 'confidence': 0.8},
            'impact_map': {
                'direct_impacts': [],
                'indirect_impacts': [],
                'affected_components': []
            },
            'risk_assessment': {
                'overall_risk': 'low',
                'risks': [],
                'breaking_changes': False,
                'requires_migration': False
            },
            'review_questions': []
        }
        result = analyzer._validate_response_data(data)
        assert result['intent']['confidence'] == 0.8
        assert result['risk_assessment']['overall_risk'] == 'low'


class TestCallApiWithRetry:
    """Test _call_api_with_retry method"""
    
    @pytest.fixture
    def analyzer(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic') as mock_client:
                a = LLMAnalyzer()
                a.client = Mock()
                return a
    
    def test_successful_call(self, analyzer):
        """Test successful API call without retry"""
        mock_response = Mock()
        analyzer.client.messages.create.return_value = mock_response
        
        result = analyzer._call_api_with_retry("test prompt", max_retries=3)
        assert result == mock_response
        assert analyzer.client.messages.create.call_count == 1
    
    def test_retry_on_rate_limit(self, analyzer):
        """Test retry on rate limit error"""
        mock_response = Mock()
        rate_limit_error = anthropic.RateLimitError(
            message="Rate limited",
            response=Mock(status_code=429),
            body={}
        )
        
        analyzer.client.messages.create.side_effect = [
            rate_limit_error,
            mock_response
        ]
        
        with patch('time.sleep'):  # Skip actual sleep
            result = analyzer._call_api_with_retry(
                "test prompt",
                max_retries=3,
                base_delay=0.01,
                max_total_wait=100
            )
        
        assert result == mock_response
        assert analyzer.client.messages.create.call_count == 2
    
    def test_retry_on_timeout(self, analyzer):
        """Test retry on timeout error"""
        mock_response = Mock()
        timeout_error = anthropic.APITimeoutError(request=Mock())
        
        analyzer.client.messages.create.side_effect = [
            timeout_error,
            mock_response
        ]
        
        with patch('time.sleep'):
            result = analyzer._call_api_with_retry(
                "test prompt",
                max_retries=3,
                base_delay=0.01,
                max_total_wait=100
            )
        
        assert result == mock_response
    
    def test_retry_on_connection_error(self, analyzer):
        """Test retry on connection error"""
        mock_response = Mock()
        conn_error = anthropic.APIConnectionError(request=Mock())
        
        analyzer.client.messages.create.side_effect = [
            conn_error,
            mock_response
        ]
        
        with patch('time.sleep'):
            result = analyzer._call_api_with_retry(
                "test prompt",
                max_retries=3,
                base_delay=0.01,
                max_total_wait=100
            )
        
        assert result == mock_response
    
    def test_retry_on_server_error(self, analyzer):
        """Test retry on 5xx server error"""
        mock_response = Mock()
        server_error = anthropic.APIStatusError(
            message="Server error",
            response=Mock(status_code=500),
            body={}
        )
        
        analyzer.client.messages.create.side_effect = [
            server_error,
            mock_response
        ]
        
        with patch('time.sleep'):
            result = analyzer._call_api_with_retry(
                "test prompt",
                max_retries=3,
                base_delay=0.01,
                max_total_wait=100
            )
        
        assert result == mock_response
    
    def test_no_retry_on_client_error(self, analyzer):
        """Test no retry on 4xx client error (except rate limit)"""
        client_error = anthropic.APIStatusError(
            message="Bad request",
            response=Mock(status_code=400),
            body={}
        )
        
        analyzer.client.messages.create.side_effect = client_error
        
        with pytest.raises(anthropic.APIStatusError):
            analyzer._call_api_with_retry("test prompt", max_retries=3)
        
        assert analyzer.client.messages.create.call_count == 1
    
    def test_exhausted_retries(self, analyzer):
        """Test RuntimeError after exhausting retries"""
        rate_limit_error = anthropic.RateLimitError(
            message="Rate limited",
            response=Mock(status_code=429),
            body={}
        )
        
        analyzer.client.messages.create.side_effect = rate_limit_error
        
        with patch('time.sleep'):
            with pytest.raises(RuntimeError, match="API call failed after"):
                analyzer._call_api_with_retry(
                    "test prompt",
                    max_retries=2,
                    base_delay=0.01,
                    max_total_wait=100
                )
    
    def test_max_total_wait_exceeded(self, analyzer):
        """Test stopping when max_total_wait is exceeded"""
        rate_limit_error = anthropic.RateLimitError(
            message="Rate limited",
            response=Mock(status_code=429),
            body={}
        )
        
        analyzer.client.messages.create.side_effect = rate_limit_error
        
        with patch('time.sleep'):
            with pytest.raises(RuntimeError):
                analyzer._call_api_with_retry(
                    "test prompt",
                    max_retries=10,
                    base_delay=10,  # Large delay
                    max_total_wait=0.001  # Very small max wait
                )


class TestAnalyze:
    """Test analyze method - full integration"""
    
    @pytest.fixture
    def analyzer(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic') as mock_client:
                a = LLMAnalyzer()
                a.client = Mock()
                return a
    
    def test_analyze_returns_semantic_analysis(self, analyzer):
        """Test analyze returns properly structured SemanticAnalysis"""
        # Mock response
        mock_response = Mock()
        mock_response.content = [Mock(text='''```json
{
    "intent": {"summary": "Test change", "reasoning": "Testing", "confidence": 0.9},
    "impact_map": {"direct_impacts": [], "indirect_impacts": [], "affected_components": []},
    "risk_assessment": {"overall_risk": "low", "risks": [], "breaking_changes": false, "requires_migration": false},
    "review_questions": []
}
```''')]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        
        analyzer.client.messages.create.return_value = mock_response
        
        commit_info = {
            'hash': 'abc123def456',
            'short_hash': 'abc123de',
            'message': 'Test commit',
            'author': 'Test <test@test.com>',
            'date': '2024-01-01T00:00:00',
        }
        
        files = [FileChange(
            path='test.py',
            change_type='modified',
            additions=10,
            deletions=5,
            diff_content='+new\n-old',
            language='python'
        )]
        
        project_context = {
            'languages': ['python'],
            'package_manager': 'pip',
            'has_tests': True,
            'has_ci': False,
            'root_files': ['setup.py'],
            'directories': ['src'],
        }
        
        result = analyzer.analyze(commit_info, files, project_context)
        
        assert result.commit_hash == 'abc123def456'
        assert result.intent.summary == 'Test change'
        assert result.intent.confidence == 0.9
        assert result.risk_assessment.overall_risk == RiskLevel.LOW
        assert result.tokens_used == 150
    
    def test_analyze_with_empty_files(self, analyzer):
        """Test analyze with empty file list"""
        mock_response = Mock()
        mock_response.content = [Mock(text='{"intent": {"summary": "Empty", "reasoning": "No files", "confidence": 0.5}}')]
        mock_response.usage.input_tokens = 50
        mock_response.usage.output_tokens = 25
        
        analyzer.client.messages.create.return_value = mock_response
        
        commit_info = {
            'hash': 'abc123',
            'short_hash': 'abc123',
            'message': 'Empty commit',
            'author': 'Test',
            'date': '2024-01-01',
        }
        
        result = analyzer.analyze(commit_info, [], {})
        
        assert result is not None
        assert result.intent.summary == 'Empty'


class TestRetryAfterHeader:
    """Test Retry-After header handling"""
    
    @pytest.fixture
    def analyzer(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('anthropic.Anthropic'):
                a = LLMAnalyzer()
                a.client = Mock()
                return a
    
    def test_retry_after_numeric(self, analyzer):
        """Test handling numeric Retry-After value"""
        mock_response = Mock()
        rate_limit_error = anthropic.RateLimitError(
            message="Rate limited",
            response=Mock(status_code=429),
            body={}
        )
        rate_limit_error.retry_after = 2.0
        
        analyzer.client.messages.create.side_effect = [
            rate_limit_error,
            mock_response
        ]
        
        with patch('time.sleep') as mock_sleep:
            result = analyzer._call_api_with_retry(
                "test",
                max_retries=3,
                base_delay=1.0,
                max_total_wait=100
            )
            
            # Should use retry_after value (plus jitter)
            assert mock_sleep.called
            actual_delay = mock_sleep.call_args[0][0]
            assert actual_delay >= 2.0  # At least retry_after value


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
