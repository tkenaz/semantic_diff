"""
Builders: parser output (a commit, or an MR range) -> ChangeSet, the unit the
analyzer reviews. Pure functions - no git, no I/O.
"""

from typing import Optional

from semantic_diff.models import ChangeSet, CommitRef


def from_commit(info: dict) -> ChangeSet:
    title, _, body = info["message"].strip().partition("\n")
    return ChangeSet(
        kind="commit",
        ref=info["short_hash"],
        head_sha=info["hash"],
        base_sha=info["parents"][0] if info["parents"] else None,
        title=title.strip(),
        description=body.strip(),
        authors=[info["author"]],
        date=info["date"],
        commits=[
            CommitRef(short_hash=info["short_hash"], subject=title.strip(), author=info["author"])
        ],
    )


def from_range(info: dict, title: Optional[str] = None, description: str = "") -> ChangeSet:
    commits = [
        CommitRef(**{k: c[k] for k in ("short_hash", "subject", "author")}) for c in info["commits"]
    ]
    if not commits:
        raise ValueError(f"Nothing to analyze: no commits in {info['short_range']}")
    return ChangeSet(
        kind="merge_request",
        ref=info["short_range"],
        head_sha=info["head"],
        base_sha=info["merge_base"],
        title=(title or "").strip() or _fallback_title(commits, info["short_range"]),
        description=description,
        authors=info["authors"],
        commits=commits,
    )


def _fallback_title(commits: list, short_range: str) -> str:
    if len(commits) == 1:
        return commits[0].subject
    return f"{len(commits)} commits ({short_range})"
