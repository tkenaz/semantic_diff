"""
Git diff parser - extracts structured information from git commits
"""

import os
from pathlib import Path
from typing import List, Optional

from git import NULL_TREE, InvalidGitRepositoryError, Repo
from git.exc import NoSuchPathError

from semantic_diff.models import FileChange


class GitParser:
    """Parses git repository information"""

    LANGUAGE_EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".sql": "sql",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".xml": "xml",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".sh": "bash",
        ".bash": "bash",
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
        except NoSuchPathError:
            raise ValueError(f"Path does not exist: {self.repo_path}")

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
            "hash": commit.hexsha,
            "short_hash": commit.hexsha[:8],
            "message": commit.message.strip(),
            "author": f"{commit.author.name} <{commit.author.email}>",
            "date": commit.committed_datetime.isoformat(),
            "parents": [p.hexsha for p in commit.parents],
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

        if not commit.parents:
            # GitPython already flips sides for NULL_TREE: this reads as
            # "empty tree -> commit", so every file comes out as added
            return [self._to_file_change(d) for d in commit.diff(NULL_TREE, create_patch=True)]

        return self._diff_to_changes(commit.parents[0], commit)

    def get_range_info(self, base_ref: str, head_ref: str) -> dict:
        """
        Get information about a change range (e.g. a merge request).
        Commits are those reachable from head but not from base, oldest first.
        """
        merge_base, head = self._resolve_range(base_ref, head_ref)
        commits = list(self.repo.iter_commits(f"{merge_base.hexsha}..{head.hexsha}", reverse=True))
        entries = [
            {
                "hash": c.hexsha,
                "short_hash": c.hexsha[:8],
                "subject": c.message.strip().split("\n")[0],
                "author": f"{c.author.name} <{c.author.email}>",
            }
            for c in commits
        ]
        return {
            "merge_base": merge_base.hexsha,
            "head": head.hexsha,
            "short_range": f"{merge_base.hexsha[:8]}..{head.hexsha[:8]}",
            "commits": entries,
            "authors": list(dict.fromkeys(e["author"] for e in entries)),
        }

    def get_range_changes(self, base_ref: str, head_ref: str) -> List[FileChange]:
        """
        Get file changes of a range with merge-request semantics:
        diff from merge-base(base, head) to head (three-dot), like GitLab's MR Changes tab.
        """
        merge_base, head = self._resolve_range(base_ref, head_ref)
        return self._diff_to_changes(merge_base, head)

    def _resolve_range(self, base_ref: str, head_ref: str):
        base = self.get_commit(base_ref)
        head = self.get_commit(head_ref)
        merge_bases = self.repo.merge_base(base, head)
        if not merge_bases:
            raise ValueError(f"No common ancestor between {base_ref} and {head_ref}")
        return merge_bases[0], head

    def _diff_to_changes(self, old, new) -> List[FileChange]:
        return [self._to_file_change(d) for d in old.diff(new, create_patch=True)]

    def _to_file_change(self, diff) -> FileChange:
        if diff.new_file:
            change_type, path = "added", diff.b_path
        elif diff.deleted_file:
            change_type, path = "deleted", diff.a_path
        elif diff.renamed_file:
            change_type, path = "renamed", f"{diff.a_path} -> {diff.b_path}"
        else:
            change_type, path = "modified", diff.b_path

        # GitPython strips the ---/+++ file headers from diff.diff, so every
        # +/- line is content - including "++i;" or "--x" in C-like code.
        diff_content = diff.diff.decode("utf-8", errors="replace")
        lines = diff_content.split("\n")
        additions = sum(1 for line in lines if line.startswith("+"))
        deletions = sum(1 for line in lines if line.startswith("-"))

        return FileChange(
            path=path,
            change_type=change_type,
            additions=additions,
            deletions=deletions,
            diff_content=diff_content,
            language=self.detect_language(diff.b_path or diff.a_path),
        )

    def get_project_context(self, max_files: int = 20) -> dict:
        """
        Get project context - file structure, main files, etc.
        Useful for understanding impact.
        """
        context = {
            "root_files": [],
            "directories": [],
            "languages": set(),
            "has_tests": False,
            "has_ci": False,
            "package_manager": None,
        }

        # Handle empty repos (no commits yet)
        try:
            tree = self.repo.tree()
        except ValueError:
            # Empty repo - no HEAD yet
            context["languages"] = []
            return context

        # Check root files
        for item in tree.traverse():
            if item.type == "blob":
                path = item.path

                # Root level important files
                if "/" not in path:
                    context["root_files"].append(path)

                    # Detect package manager
                    if path == "package.json":
                        context["package_manager"] = "npm"
                    elif path == "requirements.txt" or path == "pyproject.toml":
                        context["package_manager"] = "pip"
                    elif path == "Cargo.toml":
                        context["package_manager"] = "cargo"
                    elif path == "go.mod":
                        context["package_manager"] = "go"

                # Detect tests
                if "test" in path.lower() or "spec" in path.lower():
                    context["has_tests"] = True

                # Detect CI
                if ".github/workflows" in path or ".gitlab-ci" in path:
                    context["has_ci"] = True

                # Track languages
                lang = self.detect_language(path)
                if lang:
                    context["languages"].add(lang)

            elif item.type == "tree" and "/" not in item.path:
                context["directories"].append(item.path)

        context["languages"] = list(context["languages"])
        return context
