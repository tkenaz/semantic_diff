"""
Git diff parser - extracts structured information from git commits
"""
import os
from typing import Optional, List
from git import Repo, InvalidGitRepositoryError
from pathlib import Path

from semantic_diff.models import FileChange


class GitParser:
    """Parses git repository information"""
    
    LANGUAGE_EXTENSIONS = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.jsx': 'javascript',
        '.rs': 'rust',
        '.go': 'go',
        '.java': 'java',
        '.rb': 'ruby',
        '.php': 'php',
        '.c': 'c',
        '.cpp': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.cs': 'csharp',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.sql': 'sql',
        '.md': 'markdown',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.toml': 'toml',
        '.xml': 'xml',
        '.html': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.sh': 'bash',
        '.bash': 'bash',
    }
    
    def __init__(self, repo_path: Optional[str] = None):
        """
        Initialize parser with repository path.
        If not provided, uses current directory.
        """
        self.repo_path = repo_path or os.getcwd()
        try:
            self.repo = Repo(self.repo_path)
        except InvalidGitRepositoryError:
            raise ValueError(f"Not a git repository: {self.repo_path}")
    
    def get_commit(self, commit_hash: str):
        """Get a commit by hash (full or short)"""
        try:
            return self.repo.commit(commit_hash)
        except Exception as e:
            raise ValueError(f"Could not find commit: {commit_hash}") from e
    
    def get_commit_info(self, commit_hash: str) -> dict:
        """Get basic commit information"""
        commit = self.get_commit(commit_hash)
        return {
            'hash': commit.hexsha,
            'short_hash': commit.hexsha[:8],
            'message': commit.message.strip(),
            'author': f"{commit.author.name} <{commit.author.email}>",
            'date': commit.committed_datetime.isoformat(),
            'parents': [p.hexsha for p in commit.parents],
        }
    
    def detect_language(self, filepath: str) -> Optional[str]:
        """Detect programming language from file extension"""
        ext = Path(filepath).suffix.lower()
        return self.LANGUAGE_EXTENSIONS.get(ext)
    
    def get_file_changes(self, commit_hash: str) -> List[FileChange]:
        """
        Get all file changes for a commit.
        Returns structured FileChange objects.
        """
        commit = self.get_commit(commit_hash)
        changes = []
        
        # Handle initial commit (no parents)
        if not commit.parents:
            for item in commit.tree.traverse():
                if item.type == 'blob':
                    content = ""
                    diff_content = "[binary file]"
                    try:
                        content = item.data_stream.read().decode('utf-8', errors='replace')
                        diff_content = f"+{content}"
                    except (UnicodeDecodeError, IOError, OSError):
                        pass  # Keep defaults: empty content, binary marker
                    
                    changes.append(FileChange(
                        path=item.path,
                        change_type='added',
                        additions=len(content.split('\n')) if content else 0,
                        deletions=0,
                        diff_content=diff_content[:5000],  # Limit size
                        language=self.detect_language(item.path)
                    ))
            return changes
        
        # Normal commit with parent
        parent = commit.parents[0]
        diffs = parent.diff(commit, create_patch=True)
        
        for diff in diffs:
            # Determine change type
            if diff.new_file:
                change_type = 'added'
                path = diff.b_path
            elif diff.deleted_file:
                change_type = 'deleted'
                path = diff.a_path
            elif diff.renamed:
                change_type = 'renamed'
                path = f"{diff.a_path} -> {diff.b_path}"
            else:
                change_type = 'modified'
                path = diff.b_path or diff.a_path
            
            # Get diff content
            try:
                diff_content = diff.diff.decode('utf-8', errors='replace')
            except (UnicodeDecodeError, AttributeError, TypeError):
                diff_content = "[binary file]"
            
            # Count additions/deletions
            additions = 0
            deletions = 0
            for line in diff_content.split('\n'):
                if line.startswith('+') and not line.startswith('+++'):
                    additions += 1
                elif line.startswith('-') and not line.startswith('---'):
                    deletions += 1
            
            changes.append(FileChange(
                path=path,
                change_type=change_type,
                additions=additions,
                deletions=deletions,
                diff_content=diff_content[:5000],  # Limit size for LLM
                language=self.detect_language(path)
            ))
        
        return changes
    
    def get_project_context(self, max_files: int = 20) -> dict:
        """
        Get project context - file structure, main files, etc.
        Useful for understanding impact.
        """
        context = {
            'root_files': [],
            'directories': [],
            'languages': set(),
            'has_tests': False,
            'has_ci': False,
            'package_manager': None,
        }
        
        # Check root files
        for item in self.repo.tree().traverse():
            if item.type == 'blob':
                path = item.path
                
                # Root level important files
                if '/' not in path:
                    context['root_files'].append(path)
                    
                    # Detect package manager
                    if path == 'package.json':
                        context['package_manager'] = 'npm'
                    elif path == 'requirements.txt' or path == 'pyproject.toml':
                        context['package_manager'] = 'pip'
                    elif path == 'Cargo.toml':
                        context['package_manager'] = 'cargo'
                    elif path == 'go.mod':
                        context['package_manager'] = 'go'
                
                # Detect tests
                if 'test' in path.lower() or 'spec' in path.lower():
                    context['has_tests'] = True
                
                # Detect CI
                if '.github/workflows' in path or '.gitlab-ci' in path:
                    context['has_ci'] = True
                
                # Track languages
                lang = self.detect_language(path)
                if lang:
                    context['languages'].add(lang)
            
            elif item.type == 'tree' and '/' not in item.path:
                context['directories'].append(item.path)
        
        context['languages'] = list(context['languages'])
        return context
