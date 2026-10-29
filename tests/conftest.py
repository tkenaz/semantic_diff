"""
Shared pytest fixtures for semantic_diff tests
"""

from datetime import datetime

import pytest
from git import Actor, Repo

from semantic_diff.models import (
    ChangeSet,
    CommitRef,
    FileChange,
    Impact,
    ImpactMap,
    Intent,
    ReviewQuestion,
    Risk,
    RiskAssessment,
    RiskLevel,
    SemanticAnalysis,
)

AUTHOR = Actor("Dev One", "dev1@example.com")
OTHER = Actor("Dev Two", "dev2@example.com")


def _commit(repo, tmp_path, files: dict, message: str, author=AUTHOR, remove=()):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if files:
        repo.index.add(list(files.keys()))
    if remove:
        repo.index.remove(list(remove), working_tree=True)
    return repo.index.commit(message, author=author, committer=author)


@pytest.fixture
def mr_repo(tmp_path):
    """
    target: base ── target_only
               \\
    feature:    c1 ── c2 ── c3

    c1 touches api.py, c2 adds util.py, c3 touches api.py again.
    target_only touches docs.md after the branch point.
    """
    repo = Repo.init(tmp_path)
    base = _commit(
        repo,
        tmp_path,
        {
            "api.py": "def get():\n    return 1\n",
            "docs.md": "v1\n",
            "models.py": "".join(f"FIELD_{i} = {i}\n" for i in range(10)),
        },
        "base",
    )
    target = repo.create_head("target", base)
    feature = repo.create_head("feature", base)

    feature.checkout()
    c1 = _commit(repo, tmp_path, {"api.py": "def get():\n    return 2\n"}, "feat: return 2")
    c2 = _commit(repo, tmp_path, {"util.py": "X = 1\n"}, "feat: add util", author=OTHER)
    c3 = _commit(
        repo, tmp_path, {"api.py": "def get():\n    return 3\n"}, "fix: return 3\n\nbody text"
    )

    target.checkout()
    target_only = _commit(repo, tmp_path, {"docs.md": "v2\n"}, "docs: target moved on")

    return {
        "path": str(tmp_path),
        "repo": repo,
        "base": base,
        "commits": [c1, c2, c3],
        "target_tip": target_only,
        "head": c3,
    }


@pytest.fixture(autouse=True)
def no_real_llm_credentials(monkeypatch):
    """
    Guard: no test may reach a real LLM API. Strips credentials from the
    environment and stops .env from re-injecting them.
    """
    for name in (
        "ANTHROPIC_API_KEY",
        "SEMANTIC_DIFF_API_KEY",
        "SEMANTIC_DIFF_BASE_URL",
        "SEMANTIC_DIFF_MAX_DIFF_TOKENS",
        "SEMANTIC_DIFF_MAX_OUTPUT_TOKENS",
        "SEMANTIC_DIFF_REVIEW_DIFF_TOKENS",
        "SEMANTIC_DIFF_MAX_TURNS",
        "SEMANTIC_DIFF_MAX_INPUT_TOKENS",
        "SEMANTIC_DIFF_RULES",
        "SEMANTIC_DIFF_PROVIDER",
        "SEMANTIC_DIFF_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("semantic_diff.user_env.load_dotenv", lambda *a, **k: None)


@pytest.fixture
def temp_git_repo(tmp_path):
    """
    Create a temporary git repository with a test commit.

    Returns:
        tuple: (repo_path, Repo object, commit_hash)
    """
    # Initialize repo
    repo = Repo.init(tmp_path)

    # Configure user
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")

    # Create initial commit
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('Hello')\n")
    repo.index.add([str(test_file)])

    author = Actor("Test User", "test@example.com")
    repo.index.commit("Initial commit", author=author)

    # Create a second commit with changes
    test_file.write_text("def hello(name='World'):\n    print(f'Hello, {name}!')\n")
    repo.index.add([str(test_file)])

    second_commit = repo.index.commit("Add name parameter to hello()", author=author)

    return str(tmp_path), repo, second_commit.hexsha


@pytest.fixture
def mock_file_change():
    """Create a mock FileChange object"""
    return FileChange(
        path="src/main.py",
        change_type="modified",
        additions=10,
        deletions=5,
        diff_content="@@ -1,5 +1,10 @@\n def main():\n-    pass\n+    print('hello')",
        language="python",
    )


@pytest.fixture
def mock_semantic_analysis(mock_file_change):
    """
    Create a complete mock SemanticAnalysis object for testing formatters.

    This fixture provides realistic test data without requiring an actual LLM call.
    """
    return SemanticAnalysis(
        change_set=ChangeSet(
            kind="commit",
            ref="abc123de",
            head_sha="abc123def456789",
            base_sha="0123456789abcdef",
            title="Add user authentication feature",
            description="JWT replaces basic auth.",
            authors=["developer@example.com"],
            date="2024-12-22T10:30:00",
            commits=[
                CommitRef(
                    short_hash="abc123de",
                    subject="Add user authentication feature",
                    author="developer@example.com",
                )
            ],
        ),
        files_changed=[
            mock_file_change,
            FileChange(
                path="src/auth.py",
                change_type="added",
                additions=50,
                deletions=0,
                language="python",
            ),
        ],
        intent=Intent(
            summary="Implement user authentication with JWT tokens",
            reasoning=(
                "The commit adds a new authentication module and modifies the main "
                "application to integrate JWT-based authentication. This is part of "
                "securing the API endpoints."
            ),
            confidence=0.92,
        ),
        impact_map=ImpactMap(
            direct_impacts=[
                Impact(
                    area="Authentication flow",
                    description="New JWT-based authentication replaces basic auth",
                    severity=RiskLevel.HIGH,
                ),
                Impact(
                    area="API endpoints",
                    description="All endpoints now require valid JWT tokens",
                    severity=RiskLevel.MEDIUM,
                ),
            ],
            indirect_impacts=[
                Impact(
                    area="Client applications",
                    description="Clients must update to include JWT tokens in requests",
                    severity=RiskLevel.MEDIUM,
                ),
            ],
            affected_components=["auth", "api", "middleware", "client-sdk"],
        ),
        risk_assessment=RiskAssessment(
            overall_risk=RiskLevel.HIGH,
            breaking_changes=True,
            requires_migration=True,
            risks=[
                Risk(
                    description="Existing API clients will fail authentication",
                    severity=RiskLevel.HIGH,
                    mitigation="Provide migration guide and backward compatibility period",
                    edge_cases=[
                        "Legacy clients without JWT support",
                        "Automated scripts using basic auth",
                    ],
                ),
                Risk(
                    description="Token expiration may cause user session loss",
                    severity=RiskLevel.MEDIUM,
                    mitigation="Implement token refresh mechanism",
                    edge_cases=["Long-running operations", "Background jobs"],
                ),
            ],
        ),
        review_questions=[
            ReviewQuestion(
                question="How are existing active sessions handled during migration?",
                context=(
                    "The change replaces the authentication system but doesn't show "
                    "migration logic for currently logged-in users."
                ),
                priority=RiskLevel.HIGH,
            ),
            ReviewQuestion(
                question="Is there rate limiting on token generation endpoints?",
                context="Authentication endpoints are vulnerable to brute force attacks.",
                priority=RiskLevel.MEDIUM,
            ),
        ],
        analysis_model="claude-sonnet-5-5",
        analysis_timestamp=datetime.now().isoformat(),
        tokens_used=5423,
    )


@pytest.fixture
def mock_minimal_analysis():
    """
    Create a minimal SemanticAnalysis for edge case testing.

    Tests formatters handling of empty/minimal data.
    """
    return SemanticAnalysis(
        change_set=ChangeSet(
            kind="commit",
            ref="minimal1",
            head_sha="minimal123",
            title="Update README",
            authors=["docs@example.com"],
            date="2024-12-22T12:00:00",
        ),
        files_changed=[
            FileChange(
                path="README.md",
                change_type="modified",
                additions=2,
                deletions=1,
                language="markdown",
            ),
        ],
        intent=Intent(
            summary="Fix typo in documentation",
            reasoning="Simple documentation fix",
            confidence=0.99,
        ),
        impact_map=ImpactMap(
            direct_impacts=[],
            indirect_impacts=[],
            affected_components=["documentation"],
        ),
        risk_assessment=RiskAssessment(
            overall_risk=RiskLevel.LOW,
            breaking_changes=False,
            requires_migration=False,
            risks=[],
        ),
        review_questions=[],
        analysis_model="claude-sonnet-5-5",
        analysis_timestamp=datetime.now().isoformat(),
        tokens_used=234,
    )


@pytest.fixture
def mock_mr_analysis(mock_semantic_analysis):
    """The same analysis, but of a merge request range."""
    return mock_semantic_analysis.model_copy(
        update={
            "change_set": ChangeSet(
                kind="merge_request",
                ref="0123abcd..abc123de",
                head_sha="abc123def456789",
                base_sha="0123abcd0123abcd",
                title="PROJ-1 Add JWT authentication",
                description="Replaces basic auth.",
                authors=["Dev One <d1@x>", "Dev Two <d2@x>"],
                commits=[
                    CommitRef(
                        short_hash="11111111", subject="feat: add jwt", author="Dev One <d1@x>"
                    ),
                    CommitRef(
                        short_hash="22222222", subject="test: jwt expiry", author="Dev Two <d2@x>"
                    ),
                ],
            )
        }
    )
