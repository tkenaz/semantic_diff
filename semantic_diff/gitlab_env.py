"""
GitLab merge request pipeline context, read from predefined CI variables.
"""

from typing import Mapping

TRUNCATION_NOTE = "[description truncated by GitLab]"


def gitlab_mr_context(env: Mapping[str, str]) -> dict:
    """
    Base is CI_MERGE_REQUEST_DIFF_BASE_SHA - the merge base GitLab itself uses
    for the MR diff - so the analysis matches what reviewers see in Changes.
    """
    base = env.get("CI_MERGE_REQUEST_DIFF_BASE_SHA")
    if not base:
        raise ValueError(
            "CI_MERGE_REQUEST_DIFF_BASE_SHA not set: not a merge request pipeline "
            "(run the job with rules: if $CI_PIPELINE_SOURCE == 'merge_request_event')"
        )
    head = env.get("CI_COMMIT_SHA")
    if not head:
        raise ValueError("CI_COMMIT_SHA not set")

    description = env.get("CI_MERGE_REQUEST_DESCRIPTION", "")
    if env.get("CI_MERGE_REQUEST_DESCRIPTION_IS_TRUNCATED") == "true":
        description = f"{description}\n\n{TRUNCATION_NOTE}"

    return {
        "base": base,
        "head": head,
        "title": env.get("CI_MERGE_REQUEST_TITLE"),
        "description": description,
    }
