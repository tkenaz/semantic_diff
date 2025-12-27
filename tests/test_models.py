import pytest
from pydantic import ValidationError
from typing import List

# Import the models directly
from semantic_diff.models import (
    RiskLevel, 
    FileChange, 
    Intent, 
    Impact, 
    ImpactMap, 
    Risk, 
    RiskAssessment, 
    ReviewQuestion, 
    SemanticAnalysis
)

def test_risk_level_enum():
    """Test that all RiskLevel enum values are valid"""
    assert RiskLevel.LOW == "low"
    assert RiskLevel.MEDIUM == "medium"
    assert RiskLevel.HIGH == "high"
    assert RiskLevel.CRITICAL == "critical"

def test_file_change_defaults():
    """Test FileChange model with defaults and edge cases"""
    
    # Test with valid minimal input
    fc = FileChange(path="test.py", change_type="added")
    assert fc.path == "test.py"
    assert fc.change_type == "added"
    assert fc.additions == 0
    assert fc.deletions == 0
    assert fc.diff_content == ""
    assert fc.language is None

    # Test with large numbers
    fc_large = FileChange(
        path="large_file.py", 
        change_type="modified", 
        additions=1_000_000, 
        deletions=500_000
    )
    assert fc_large.additions == 1_000_000
    assert fc_large.deletions == 500_000

def test_intent_validation():
    """Test Intent model with confidence validation"""
    # Valid confidence values
    Intent(summary="Test", reasoning="Details", confidence=0)
    Intent(summary="Test", reasoning="Details", confidence=1)
    Intent(summary="Test", reasoning="Details", confidence=0.5)

    # Invalid confidence values
    with pytest.raises(ValidationError):
        Intent(summary="Test", reasoning="Details", confidence=-0.1)
    with pytest.raises(ValidationError):
        Intent(summary="Test", reasoning="Details", confidence=1.1)

def test_impact_and_impact_map():
    """Test Impact and ImpactMap nested structures"""
    # Test single impact
    impact = Impact(area="Database", description="Schema change", severity=RiskLevel.MEDIUM)
    assert impact.area == "Database"
    assert impact.severity == RiskLevel.MEDIUM

    # Test ImpactMap with Unicode and empty lists
    impact_map = ImpactMap(
        direct_impacts=[
            Impact(area="Интерфейс 🚀", description="Обновление UI", severity=RiskLevel.LOW)
        ],
        indirect_impacts=[],
        affected_components=["frontend", "backend"]
    )
    assert len(impact_map.direct_impacts) == 1
    assert len(impact_map.indirect_impacts) == 0
    assert impact_map.direct_impacts[0].area == "Интерфейс 🚀"

def test_risk_and_risk_assessment():
    """Test Risk and RiskAssessment models"""
    # Test Risk
    risk = Risk(
        description="Potential data loss", 
        severity=RiskLevel.HIGH,
        edge_cases=["Large datasets"]
    )
    assert risk.mitigation is None
    assert risk.edge_cases == ["Large datasets"]

    # Test RiskAssessment with defaults
    risk_assessment = RiskAssessment(
        overall_risk=RiskLevel.MEDIUM,
        risks=[risk]
    )
    assert risk_assessment.breaking_changes is False
    assert risk_assessment.requires_migration is False

def test_review_question():
    """Test ReviewQuestion with default priority"""
    question = ReviewQuestion(
        question="Why this approach?", 
        context="Code refactoring"
    )
    assert question.priority == RiskLevel.MEDIUM

def test_semantic_analysis_full_model():
    """Test complete SemanticAnalysis with nested models"""
    analysis = SemanticAnalysis(
        commit_hash="abc123",
        commit_message="Add new feature",
        author="John Doe",
        date="2023-12-25",
        files_changed=[
            FileChange(path="main.py", change_type="added")
        ],
        intent=Intent(
            summary="Implement core functionality", 
            reasoning="Needed for new feature", 
            confidence=0.9
        ),
        impact_map=ImpactMap(
            direct_impacts=[
                Impact(area="Core Logic", description="New algorithm", severity=RiskLevel.LOW)
            ]
        ),
        risk_assessment=RiskAssessment(
            overall_risk=RiskLevel.LOW,
            breaking_changes=False
        ),
        review_questions=[
            ReviewQuestion(
                question="Performance implications?", 
                context="New algorithm"
            )
        ],
        analysis_model="GPT-4",
        analysis_timestamp="2023-12-25T12:00:00",
        tokens_used=500
    )
    
    # Validate nested structures
    assert len(analysis.files_changed) == 1
    assert len(analysis.review_questions) == 1
    assert analysis.intent.confidence == 0.9

def test_invalid_risk_level():
    """Test that invalid RiskLevel values are not allowed"""
    with pytest.raises(ValueError):
        RiskLevel("invalid_level")
