"""
Data models for semantic diff analysis
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FileChange(BaseModel):
    """Represents a single file change in a commit"""
    path: str
    change_type: str  # added, modified, deleted, renamed
    additions: int = 0
    deletions: int = 0
    diff_content: str = ""
    language: Optional[str] = None


class Intent(BaseModel):
    """What the developer was trying to accomplish"""
    summary: str = Field(description="One-line summary of the intent")
    reasoning: str = Field(description="Detailed reasoning behind this assessment")
    confidence: float = Field(ge=0, le=1, description="Confidence in this assessment")


class Impact(BaseModel):
    """A single impact point"""
    area: str = Field(description="What area is affected")
    description: str = Field(description="How it's affected")
    severity: RiskLevel = Field(description="How significant is this impact")


class ImpactMap(BaseModel):
    """Map of all areas impacted by the change"""
    direct_impacts: List[Impact] = Field(default_factory=list)
    indirect_impacts: List[Impact] = Field(default_factory=list)
    affected_components: List[str] = Field(default_factory=list)


class Risk(BaseModel):
    """A single identified risk"""
    description: str
    severity: RiskLevel
    mitigation: Optional[str] = None
    edge_cases: List[str] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    """Overall risk assessment"""
    overall_risk: RiskLevel
    risks: List[Risk] = Field(default_factory=list)
    breaking_changes: bool = False
    requires_migration: bool = False


class ReviewQuestion(BaseModel):
    """A question for the code author"""
    question: str
    context: str
    priority: RiskLevel = RiskLevel.MEDIUM


class SemanticAnalysis(BaseModel):
    """Complete semantic analysis of a commit"""
    commit_hash: str
    commit_message: str
    author: str
    date: str
    files_changed: List[FileChange]
    
    intent: Intent
    impact_map: ImpactMap
    risk_assessment: RiskAssessment
    review_questions: List[ReviewQuestion]
    
    # Metadata
    analysis_model: str
    analysis_timestamp: str
    tokens_used: int = 0
