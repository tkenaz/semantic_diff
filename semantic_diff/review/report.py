"""
What a review produces: findings tied to lines, a verdict, and an honest
account of how the review went (turns, tokens, files read, limits hit).
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from semantic_diff.models import ChangeSet, DiffCoverage, RiskLevel

Verdict = Literal["approve", "comment", "request_changes"]
Limit = Literal["turns", "tokens", "context"]
# Where the cited line exists: after the change, only before it, or nowhere
Citation = Literal["head", "base", "no_such_line", "no_such_file"]


class SubmittedFinding(BaseModel):
    """A finding as the model must send it - it cannot add its own checks"""

    model_config = {"extra": "forbid"}

    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    severity: RiskLevel
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    suggestion: Optional[str] = None


class Finding(SubmittedFinding):
    """A finding as reported, with the checks done on it"""

    citation: Citation
    seen: bool  # the file was in the shown diff or read with a tool


class SubmittedReview(BaseModel):
    """The submit_review arguments, as the model must send them"""

    model_config = {"extra": "forbid"}

    summary: str = Field(min_length=1)
    verdict: Verdict
    findings: List[SubmittedFinding] = Field(default_factory=list)


class ReviewStats(BaseModel):
    turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    files_read: List[str] = Field(default_factory=list)
    submitted: bool = False
    limit_hit: Optional[Limit] = None  # the review was wrapped up early by this limit


class ReviewReport(BaseModel):
    # Bump on breaking JSON changes
    schema_version: int = 1
    change_set: ChangeSet
    verdict: Optional[Verdict]  # None: the model never submitted
    summary: str
    findings: List[Finding]
    stats: ReviewStats
    diff_coverage: DiffCoverage
    review_model: str
    review_timestamp: str
