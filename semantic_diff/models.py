"""
Data models for semantic diff analysis
"""

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, computed_field


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


class CommitRef(BaseModel):
    """One commit inside a change set"""

    short_hash: str
    subject: str
    author: str


class ChangeSet(BaseModel):
    """The unit under review: a single commit or a merge request range"""

    kind: Literal["commit", "merge_request"]
    ref: str  # short hash, or "<merge-base>..<head>" for a range
    head_sha: str
    base_sha: Optional[str] = None
    title: str
    description: str = ""
    authors: List[str] = Field(default_factory=list)
    date: Optional[str] = None
    commits: List[CommitRef] = Field(default_factory=list)


class DiffCoverage(BaseModel):
    """How much of the change the model actually saw under the token budget"""

    budget_tokens: int
    shown_lines: int  # changed (+/-) lines included in the prompt
    total_lines: int  # changed lines across all non-noise files
    trimmed: List[str] = Field(default_factory=list)  # shown in part (whole hunks)
    omitted: List[str] = Field(default_factory=list)  # not shown, budget exhausted
    noise: List[str] = Field(default_factory=list)  # lock/generated/binary, listed only

    @computed_field
    @property
    def percent(self) -> int:
        # Floor: 999 of 1000 lines must not read as "100%" in a report
        if self.total_lines == 0:
            return 100
        return self.shown_lines * 100 // self.total_lines


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
    """Complete semantic analysis of a change set (commit or merge request)"""

    change_set: ChangeSet
    files_changed: List[FileChange]

    intent: Intent
    impact_map: ImpactMap
    risk_assessment: RiskAssessment
    review_questions: List[ReviewQuestion]

    # Metadata
    analysis_model: str
    analysis_timestamp: str
    tokens_used: int = 0
    diff_coverage: Optional[DiffCoverage] = None
