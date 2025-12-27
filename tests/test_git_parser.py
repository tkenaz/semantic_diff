"""
Tests for GitParser - git diff parser
"""
import os
import tempfile
import shutil
from pathlib import Path
import pytest
from git import Repo, Actor

from semantic_diff.parsers.git_parser import GitParser
from semantic_diff.models import FileChange


class TestGitParserInit:
    """Test GitParser initialization"""
    
    def test_init_with_valid_repo(self, tmp_path):
        """Test initialization with valid git repository"""
        repo = Repo.init(tmp_path)
        parser = GitParser(str(tmp_path))
        assert parser.repo_path == str(tmp_path)
        assert parser.repo is not None
    
    def test_init_with_invalid_path(self, tmp_path):
        """Test initialization with non-git directory raises ValueError"""
        non_git_dir = tmp_path / "not_a_repo"
        non_git_dir.mkdir()
        
        with pytest.raises(ValueError, match="Not a git repository"):
            GitParser(str(non_git_dir))
    
    def test_init_with_nonexistent_path(self):
        """Test initialization with nonexistent path raises ValueError"""
        with pytest.raises(ValueError, match="Not a git repository"):
            GitParser("/nonexistent/path/to/repo")
    
    def test_init_with_current_directory(self, tmp_path, monkeypatch):
        """Test initialization without path uses current directory"""
        repo = Repo.init(tmp_path)
        monkeypatch.chdir(tmp_path)
        
        parser = GitParser()
        assert parser.repo_path == str(tmp_path)


class TestDetectLanguage:
    """Test language detection from file extensions"""
    
    def test_detect_known_extensions(self):
        """Test detection of known file extensions"""
        parser = GitParser.__new__(GitParser)
        
        test_cases = [
            ('file.py', 'python'),
            ('script.js', 'javascript'),
            ('component.tsx', 'typescript'),
            ('main.rs', 'rust'),
            ('app.go', 'go'),
            ('Main.java', 'java'),
            ('script.rb', 'ruby'),
            ('index.php', 'php'),
            ('program.c', 'c'),
            ('program.cpp', 'cpp'),
            ('header.h', 'c'),
            ('header.hpp', 'cpp'),
            ('app.cs', 'csharp'),
            ('App.swift', 'swift'),
            ('Main.kt', 'kotlin'),
            ('App.scala', 'scala'),
            ('query.sql', 'sql'),
            ('README.md', 'markdown'),
            ('config.json', 'json'),
            ('config.yaml', 'yaml'),
            ('config.yml', 'yaml'),
            ('config.toml', 'toml'),
            ('data.xml', 'xml'),
            ('index.html', 'html'),
            ('style.css', 'css'),
            ('style.scss', 'scss'),
            ('script.sh', 'bash'),
            ('script.bash', 'bash'),
        ]
        
        for filepath, expected_lang in test_cases:
            assert parser.detect_language(filepath) == expected_lang
    
    def test_detect_unknown_extension(self):
        """Test detection returns None for unknown extensions"""
        parser = GitParser.__new__(GitParser)
        
        assert parser.detect_language('file.unknown') is None
        assert parser.detect_language('file.xyz') is None
        assert parser.detect_language('file.abc123') is None
    
    def test_detect_no_extension(self):
        """Test detection returns None for files without extension"""
        parser = GitParser.__new__(GitParser)
        
        assert parser.detect_language('Makefile') is None
        assert parser.detect_language('README') is None
        assert parser.detect_language('LICENSE') is None
    
    def test_detect_case_insensitive(self):
        """Test detection is case insensitive"""
        parser = GitParser.__new__(GitParser)
        
        assert parser.detect_language('File.PY') == 'python'
        assert parser.detect_language('File.JS') == 'javascript'
        assert parser.detect_language('File.Py') == 'python'


class TestGetCommit:
    """Test getting commit objects"""
    
    def test_get_commit_valid_hash(self, tmp_path):
        """Test getting commit with valid hash"""
        repo = Repo.init(tmp_path)
        file_path = tmp_path / "test.txt"
        file_path.write_text("test content")
        repo.index.add(['test.txt'])
        commit = repo.index.commit("Initial commit")
        
        parser = GitParser(str(tmp_path))
        retrieved_commit = parser.get_commit(commit.hexsha)
        
        assert retrieved_commit.hexsha == commit.hexsha
        assert retrieved_commit.message == "Initial commit\n"
    
    def test_get_commit_short_hash(self, tmp_path):
        """Test getting commit with short hash"""
        repo = Repo.init(tmp_path)
        file_path = tmp_path / "test.txt"
        file_path.write_text("test content")
        repo.index.add(['test.txt'])
        commit = repo.index.commit("Initial commit")
        
        parser = GitParser(str(tmp_path))
        short_hash = commit.hexsha[:8]
        retrieved_commit = parser.get_commit(short_hash)
        
        assert retrieved_commit.hexsha == commit.hexsha
    
    def test_get_commit_invalid_hash(self, tmp_path):
        """Test getting commit with invalid hash raises ValueError"""
        repo = Repo.init(tmp_path)
        file_path = tmp_path / "test.txt"
        file_path.write_text("test content")
        repo.index.add(['test.txt'])
        repo.index.commit("Initial commit")
        
        parser = GitParser(str(tmp_path))
        
        with pytest.raises(ValueError, match="Could not find commit"):
            parser.get_commit("invalid_hash_123")
    
    def test_get_commit_nonexistent_hash(self, tmp_path):
        """Test getting commit with nonexistent but valid-looking hash"""
        repo = Repo.init(tmp_path)
        file_path = tmp_path / "test.txt"
        file_path.write_text("test content")
        repo.index.add(['test.txt'])
        repo.index.commit("Initial commit")
        
        parser = GitParser(str(tmp_path))
        
        with pytest.raises(ValueError, match="Could not find commit"):
            parser.get_commit("a" * 40)


class TestGetCommitInfo:
    """Test getting commit information"""
    
    def test_get_commit_info_structure(self, tmp_path):
        """Test commit info returns correct structure"""
        repo = Repo.init(tmp_path)
        author = Actor("Test Author", "test@example.com")
        
        file_path = tmp_path / "test.txt"
        file_path.write_text("test content")
        repo.index.add(['test.txt'])
        commit = repo.index.commit("Test commit message", author=author, committer=author)
        
        parser = GitParser(str(tmp_path))
        info = parser.get_commit_info(commit.hexsha)
        
        assert 'hash' in info
        assert 'short_hash' in info
        assert 'message' in info
        assert 'author' in info
        assert 'date' in info
        assert 'parents' in info
        
        assert info['hash'] == commit.hexsha
        assert info['short_hash'] == commit.hexsha[:8]
        assert info['message'] == "Test commit message"
        assert "Test Author" in info['author']
        assert "test@example.com" in info['author']
        assert isinstance(info['date'], str)
        assert isinstance(info['parents'], list)
    
    def test_get_commit_info_initial_commit(self, tmp_path):
        """Test commit info for initial commit (no parents)"""
        repo = Repo.init(tmp_path)
        file_path = tmp_path / "test.txt"
        file_path.write_text("test content")
        repo.index.add(['test.txt'])
        commit = repo.index.commit("Initial commit")
        
        parser = GitParser(str(tmp_path))
        info = parser.get_commit_info(commit.hexsha)
        
        assert info['parents'] == []
    
    def test_get_commit_info_with_parent(self, tmp_path):
        """Test commit info includes parent commits"""
        repo = Repo.init(tmp_path)
        
        # First commit
        file_path = tmp_path / "test.txt"
        file_path.write_text("test content")
        repo.index.add(['test.txt'])
        first_commit = repo.index.commit("First commit")
        
        # Second commit
        file_path.write_text("updated content")
        repo.index.add(['test.txt'])
        second_commit = repo.index.commit("Second commit")
        
        parser = GitParser(str(tmp_path))
        info = parser.get_commit_info(second_commit.hexsha)
        
        assert len(info['parents']) == 1
        assert info['parents'][0] == first_commit.hexsha


class TestGetFileChanges:
    """Test getting file changes from commits"""
    
    def test_get_file_changes_initial_commit(self, tmp_path):
        """Test file changes for initial commit (no parents)"""
        repo = Repo.init(tmp_path)
        
        file1 = tmp_path / "test.py"
        file1.write_text("print('hello')\n")
        file2 = tmp_path / "README.md"
        file2.write_text("# Test\n")
        
        repo.index.add(['test.py', 'README.md'])
        commit = repo.index.commit("Initial commit")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 2
        assert all(isinstance(change, FileChange) for change in changes)
        
        paths = [change.path for change in changes]
        assert 'test.py' in paths
        assert 'README.md' in paths
        
        for change in changes:
            assert change.change_type == 'added'
            assert change.additions > 0
            assert change.deletions == 0
    
    def test_get_file_changes_normal_commit(self, tmp_path):
        """Test file changes for normal commit with parent"""
        repo = Repo.init(tmp_path)
        
        # Initial commit
        file_path = tmp_path / "test.py"
        file_path.write_text("line1\nline2\n")
        repo.index.add(['test.py'])
        repo.index.commit("Initial commit")
        
        # Modify file
        file_path.write_text("line1\nline2 modified\nline3\n")
        repo.index.add(['test.py'])
        commit = repo.index.commit("Modify file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 1
        change = changes[0]
        
        assert change.path == 'test.py'
        assert change.change_type == 'modified'
        assert change.language == 'python'
        assert change.additions > 0
        assert change.deletions > 0
        assert len(change.diff_content) > 0
    
    def test_get_file_changes_added_file(self, tmp_path):
        """Test file changes for added file"""
        repo = Repo.init(tmp_path)
        
        # Initial commit
        file1 = tmp_path / "test1.py"
        file1.write_text("content1")
        repo.index.add(['test1.py'])
        repo.index.commit("Initial commit")
        
        # Add new file
        file2 = tmp_path / "test2.py"
        file2.write_text("content2")
        repo.index.add(['test2.py'])
        commit = repo.index.commit("Add file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 1
        change = changes[0]
        
        assert change.path == 'test2.py'
        assert change.change_type == 'added'
        assert change.additions > 0
        assert change.deletions == 0
    
    def test_get_file_changes_deleted_file(self, tmp_path):
        """Test file changes for deleted file"""
        repo = Repo.init(tmp_path)
        
        # Initial commit
        file_path = tmp_path / "test.py"
        file_path.write_text("content")
        repo.index.add(['test.py'])
        repo.index.commit("Initial commit")
        
        # Delete file
        file_path.unlink()
        repo.index.remove(['test.py'])
        commit = repo.index.commit("Delete file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 1
        change = changes[0]
        
        assert change.path == 'test.py'
        assert change.change_type == 'deleted'
        assert change.deletions > 0
    
    def test_get_file_changes_renamed_file(self, tmp_path):
        """Test file changes for renamed file"""
        repo = Repo.init(tmp_path)
        
        # Initial commit
        file_path = tmp_path / "old_name.py"
        file_path.write_text("content")
        repo.index.add(['old_name.py'])
        repo.index.commit("Initial commit")
        
        # Rename file
        new_path = tmp_path / "new_name.py"
        file_path.rename(new_path)
        repo.index.remove(['old_name.py'])
        repo.index.add(['new_name.py'])
        commit = repo.index.commit("Rename file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) >= 1
        
        # Check if any change is marked as renamed
        renamed_changes = [c for c in changes if c.change_type == 'renamed']
        if renamed_changes:
            change = renamed_changes[0]
            assert 'old_name.py' in change.path
            assert 'new_name.py' in change.path
    
    def test_get_file_changes_binary_file(self, tmp_path):
        """Test file changes with binary file"""
        repo = Repo.init(tmp_path)
        
        # Initial commit
        file1 = tmp_path / "text.txt"
        file1.write_text("text content")
        repo.index.add(['text.txt'])
        repo.index.commit("Initial commit")
        
        # Add binary file
        binary_file = tmp_path / "image.bin"
        binary_file.write_bytes(b'\x00\x01\x02\x03\xff\xfe\xfd')
        repo.index.add(['image.bin'])
        commit = repo.index.commit("Add binary file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 1
        change = changes[0]
        
        assert change.path == 'image.bin'
        assert '[binary file]' in change.diff_content
    
    def test_get_file_changes_empty_commit(self, tmp_path):
        """Test file changes for commit with no changes (edge case)"""
        repo = Repo.init(tmp_path)
        
        # Initial commit
        file_path = tmp_path / "test.txt"
        file_path.write_text("content")
        repo.index.add(['test.txt'])
        repo.index.commit("Initial commit")
        
        # Empty commit (no changes)
        commit = repo.index.commit("Empty commit", skip_hooks=True)
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 0
    
    def test_get_file_changes_merge_commit(self, tmp_path):
        """Test file changes for merge commit"""
        repo = Repo.init(tmp_path)
        
        # Initial commit on main
        file_path = tmp_path / "test.txt"
        file_path.write_text("main content")
        repo.index.add(['test.txt'])
        repo.index.commit("Initial commit")
        
        # Create branch
        branch = repo.create_head('feature')
        branch.checkout()
        
        # Commit on branch
        file_path.write_text("branch content")
        repo.index.add(['test.txt'])
        branch_commit = repo.index.commit("Branch commit")
        
        # Switch back to main
        repo.heads.master.checkout()
        
        # Merge branch
        repo.git.merge('feature')
        merge_commit = repo.head.commit
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(merge_commit.hexsha)
        
        # Merge commits should still return changes
        assert isinstance(changes, list)
    
    def test_get_file_changes_language_detection(self, tmp_path):
        """Test that language is correctly detected for changed files"""
        repo = Repo.init(tmp_path)
        
        files = {
            'script.py': 'python',
            'app.js': 'javascript',
            'main.rs': 'rust',
            'README.md': 'markdown',
            'unknown.xyz': None,
        }
        
        for filename, expected_lang in files.items():
            (tmp_path / filename).write_text(f"content of {filename}")
        
        repo.index.add(list(files.keys()))
        commit = repo.index.commit("Add multiple files")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == len(files)
        
        for change in changes:
            expected_lang = files[change.path]
            assert change.language == expected_lang
    
    def test_get_file_changes_diff_truncation(self, tmp_path):
        """Test that large diffs are truncated to 5000 chars"""
        repo = Repo.init(tmp_path)
        
        # Create file with very long content
        large_content = "line\n" * 2000  # More than 5000 chars
        file_path = tmp_path / "large.txt"
        file_path.write_text(large_content)
        
        repo.index.add(['large.txt'])
        commit = repo.index.commit("Add large file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 1
        change = changes[0]
        
        # Diff should be truncated
        assert len(change.diff_content) <= 5000


class TestGetProjectContext:
    """Test getting project context"""
    
    def test_get_project_context_structure(self, tmp_path):
        """Test project context returns correct structure"""
        repo = Repo.init(tmp_path)
        
        # Create some files
        (tmp_path / "README.md").write_text("# Project")
        (tmp_path / "main.py").write_text("print('hello')")
        
        repo.index.add(['README.md', 'main.py'])
        repo.index.commit("Initial commit")
        
        parser = GitParser(str(tmp_path))
        context = parser.get_project_context()
        
        assert 'root_files' in context
        assert 'directories' in context
        assert 'languages' in context
        assert 'has_tests' in context
        assert 'has_ci' in context
        assert 'package_manager' in context
        
        assert isinstance(context['root_files'], list)
        assert isinstance(context['directories'], list)
        assert isinstance(context['languages'], list)
        assert isinstance(context['has_tests'], bool)
        assert isinstance(context['has_ci'], bool)
    
    def test_get_project_context_detects_languages(self, tmp_path):
        """Test project context detects languages"""
        repo = Repo.init(tmp_path)
        
        (tmp_path / "script.py").write_text("python")
        (tmp_path / "app.js").write_text("javascript")
        (tmp_path / "main.rs").write_text("rust")
        
        repo.index.add(['script.py', 'app.js', 'main.rs'])
        repo.index.commit("Add files")
        
        parser = GitParser(str(tmp_path))
        context = parser.get_project_context()
        
        assert 'python' in context['languages']
        assert 'javascript' in context['languages']
        assert 'rust' in context['languages']
    
    def test_get_project_context_detects_tests(self, tmp_path):
        """Test project context detects test files"""
        repo = Repo.init(tmp_path)
        
        (tmp_path / "test_main.py").write_text("test")
        repo.index.add(['test_main.py'])
        repo.index.commit("Add test")
        
        parser = GitParser(str(tmp_path))
        context = parser.get_project_context()
        
        assert context['has_tests'] is True
    
    def test_get_project_context_detects_tests_spec(self, tmp_path):
        """Test project context detects spec files as tests"""
        repo = Repo.init(tmp_path)
        
        (tmp_path / "main.spec.js").write_text("spec")
        repo.index.add(['main.spec.js'])
        repo.index.commit("Add spec")
        
        parser = GitParser(str(tmp_path))
        context = parser.get_project_context()
        
        assert context['has_tests'] is True
    
    def test_get_project_context_detects_ci(self, tmp_path):
        """Test project context detects CI configuration"""
        repo = Repo.init(tmp_path)
        
        ci_dir = tmp_path / ".github" / "workflows"
        ci_dir.mkdir(parents=True)
        (ci_dir / "ci.yml").write_text("ci config")
        
        repo.index.add(['.github/workflows/ci.yml'])
        repo.index.commit("Add CI")
        
        parser = GitParser(str(tmp_path))
        context = parser.get_project_context()
        
        assert context['has_ci'] is True
    
    def test_get_project_context_detects_package_managers(self, tmp_path):
        """Test project context detects package managers"""
        test_cases = [
            ('package.json', 'npm'),
            ('requirements.txt', 'pip'),
            ('pyproject.toml', 'pip'),
            ('Cargo.toml', 'cargo'),
            ('go.mod', 'go'),
        ]
        
        for filename, expected_pm in test_cases:
            repo = Repo.init(tmp_path)
            (tmp_path / filename).write_text("config")
            repo.index.add([filename])
            repo.index.commit("Add package file")
            
            parser = GitParser(str(tmp_path))
            context = parser.get_project_context()
            
            assert context['package_manager'] == expected_pm
            
            # Cleanup for next iteration
            shutil.rmtree(tmp_path / ".git")
            (tmp_path / filename).unlink()
    
    def test_get_project_context_root_files(self, tmp_path):
        """Test project context lists root files"""
        repo = Repo.init(tmp_path)
        
        (tmp_path / "README.md").write_text("readme")
        (tmp_path / "LICENSE").write_text("license")
        
        subdir = tmp_path / "src"
        subdir.mkdir()
        (subdir / "main.py").write_text("code")
        
        repo.index.add(['README.md', 'LICENSE', 'src/main.py'])
        repo.index.commit("Add files")
        
        parser = GitParser(str(tmp_path))
        context = parser.get_project_context()
        
        assert 'README.md' in context['root_files']
        assert 'LICENSE' in context['root_files']
        assert 'src/main.py' not in context['root_files']
    
    def test_get_project_context_directories(self, tmp_path):
        """Test project context lists root directories"""
        repo = Repo.init(tmp_path)
        
        dirs = ['src', 'tests', 'docs']
        for dirname in dirs:
            dir_path = tmp_path / dirname
            dir_path.mkdir()
            (dir_path / "file.txt").write_text("content")
        
        repo.index.add(['src/file.txt', 'tests/file.txt', 'docs/file.txt'])
        repo.index.commit("Add directories")
        
        parser = GitParser(str(tmp_path))
        context = parser.get_project_context()
        
        for dirname in dirs:
            assert dirname in context['directories']
    
    def test_get_project_context_empty_repo(self, tmp_path):
        """Test project context with empty repository"""
        repo = Repo.init(tmp_path)
        
        parser = GitParser(str(tmp_path))
        context = parser.get_project_context()
        
        assert context['root_files'] == []
        assert context['directories'] == []
        assert context['languages'] == []
        assert context['has_tests'] is False
        assert context['has_ci'] is False
        assert context['package_manager'] is None


class TestEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_empty_repository_no_commits(self, tmp_path):
        """Test operations on empty repository with no commits"""
        repo = Repo.init(tmp_path)
        parser = GitParser(str(tmp_path))
        
        # Should raise error when trying to get non-existent commit
        with pytest.raises(ValueError):
            parser.get_commit("HEAD")
    
    def test_file_with_special_characters(self, tmp_path):
        """Test handling files with special characters in names"""
        repo = Repo.init(tmp_path)
        
        special_file = tmp_path / "file with spaces.py"
        special_file.write_text("content")
        repo.index.add(['file with spaces.py'])
        commit = repo.index.commit("Add special file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 1
        assert changes[0].path == 'file with spaces.py'
    
    def test_unicode_content(self, tmp_path):
        """Test handling files with unicode content"""
        repo = Repo.init(tmp_path)
        
        unicode_file = tmp_path / "unicode.txt"
        unicode_file.write_text("Hello 世界 🌍 Привет")
        repo.index.add(['unicode.txt'])
        commit = repo.index.commit("Add unicode file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 1
        assert 'unicode.txt' in changes[0].path
    
    def test_deeply_nested_files(self, tmp_path):
        """Test handling deeply nested directory structures"""
        repo = Repo.init(tmp_path)
        
        deep_path = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep_path.mkdir(parents=True)
        deep_file = deep_path / "deep.py"
        deep_file.write_text("deep content")
        
        repo.index.add(['a/b/c/d/e/deep.py'])
        commit = repo.index.commit("Add deep file")
        
        parser = GitParser(str(tmp_path))
        changes = parser.get_file_changes(commit.hexsha)
        
        assert len(changes) == 1
        assert changes[0].path == 'a/b/c/d/e/deep.py'
        assert changes[0].language == 'python'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
