"""
Shared pytest fixtures for semantic_diff tests
"""

from datetime import datetime

import pytest
from git import Actor, Repo

from semantic_diff.models import (
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
        commit_hash="abc123def456789",
        commit_message="Add user authentication feature",
        author="developer@example.com",
        date="2024-12-22T10:30:00",
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
        analysis_model="claude-sonnet-4-5-20250929",
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
        commit_hash="minimal123",
        commit_message="Update README",
        author="docs@example.com",
        date="2024-12-22T12:00:00",
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
        analysis_model="claude-sonnet-4-5-20250929",
        analysis_timestamp=datetime.now().isoformat(),
        tokens_used=234,
    )
