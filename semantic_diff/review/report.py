"""
What a review produces: findings tied to lines, a verdict, and an honest
account of how the review went (turns, tokens, files read, limits hit).

Findings come in two channels (schema_version 2):

- `findings` — cited: backed by a rule card from the configured corpus
  (`rule_id` + `source` copied verbatim) AND by evidence that holds up
  (the cited line exists, the file was seen, the quoted evidence is in the
  diff). Gating consumers (CI `fail_on_risk`) read ONLY this channel,
  through `risk_level`.
- `uncited` — everything else: observations without a card, citations of
  cards that do not exist, findings whose evidence did not check out.
  Severity stays honest, but this channel is informational and must never
  flip a pass to a fail.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from semantic_diff.models import ChangeSet, DiffCoverage, RiskLevel

Verdict = Literal["approve", "comment", "request_changes"]
Limit = Literal["turns", "tokens", "context"]
# Where the cited line exists: after the change, only before it, or nowhere
Citation = Literal["head", "base", "no_such_line", "no_such_file"]
# Why a finding was kept out of the cited channel
UncitedReason = Literal["no_rule", "unknown_rule_id", "no_evidence"]

SEVERITY_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]


class SubmittedFinding(BaseModel):
    """A finding as the model must send it - it cannot add its own checks"""

    model_config = {"extra": "forbid"}

    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    severity: RiskLevel
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    suggestion: Optional[str] = None
    # Provenance: only when a rule card backs the finding, copied verbatim
    rule_id: Optional[str] = None
    source: Optional[str] = None
    # The diff line(s) the finding rests on, quoted verbatim
    evidence: Optional[str] = None


class Finding(SubmittedFinding):
    """A finding as reported, with the checks done on it"""

    citation: Citation
    seen: bool  # the file was in the shown diff or read with a tool
    uncited_reason: Optional[UncitedReason] = None  # None: cited, may gate


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
    schema_version: int = 2
    change_set: ChangeSet
    verdict: Optional[Verdict]  # None: the model never submitted
    summary: str
    findings: List[Finding]  # cited channel: the only one gates may read
    uncited: List[Finding] = Field(default_factory=list)  # informational, never gates
    # The gate value: the worst severity among cited findings, None without any.
    # CI `fail_on_risk` reads this and nothing else.
    risk_level: Optional[RiskLevel] = None
    stats: ReviewStats
    diff_coverage: DiffCoverage
    review_model: str
    review_timestamp: str


def worst_severity(findings: List[Finding]) -> Optional[RiskLevel]:
    if not findings:
        return None
    return max(findings, key=lambda f: SEVERITY_ORDER.index(f.severity)).severity
