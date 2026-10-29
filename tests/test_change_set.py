"""
Tests for ChangeSet builders - turning parser output (a commit or an MR range)
into the unit the analyzer reviews - and for reading GitLab MR pipeline context.
"""

import pytest

from semantic_diff.change_set import from_commit, from_range
from semantic_diff.gitlab_env import gitlab_mr_context
from semantic_diff.models import ChangeSet, CommitRef

COMMIT_INFO = {
    "hash": "a" * 40,
    "short_hash": "a" * 8,
    "message": "fix(auth): reject expired tokens\n\nThe check used <= instead of <.",
    "author": "Dev One <dev1@example.com>",
    "date": "2026-10-12T10:00:00+02:00",
    "parents": ["p" * 40],
}


def _range_info(*subjects_and_authors):
    commits = [
        {"hash": f"{i}" * 40, "short_hash": f"{i}" * 8, "subject": subject, "author": author}
        for i, (subject, author) in enumerate(subjects_and_authors, start=1)
    ]
    return {
        "merge_base": "b" * 40,
        "head": "h" * 40,
        "short_range": f"{'b' * 8}..{'h' * 8}",
        "commits": commits,
        "authors": list(dict.fromkeys(c["author"] for c in commits)),
    }


class TestFromCommit:
    def test_maps_commit_info(self):
        change_set = from_commit(COMMIT_INFO)

        assert change_set == ChangeSet(
            kind="commit",
            ref="a" * 8,
            head_sha="a" * 40,
            base_sha="p" * 40,
            title="fix(auth): reject expired tokens",
            description="The check used <= instead of <.",
            authors=["Dev One <dev1@example.com>"],
            date="2026-10-12T10:00:00+02:00",
            commits=[
                CommitRef(
                    short_hash="a" * 8,
                    subject="fix(auth): reject expired tokens",
                    author="Dev One <dev1@example.com>",
                )
            ],
        )

    def test_initial_commit_has_no_base(self):
        change_set = from_commit({**COMMIT_INFO, "parents": []})

        assert change_set.base_sha is None

    def test_subject_only_message_has_empty_description(self):
        change_set = from_commit({**COMMIT_INFO, "message": "chore: bump"})

        assert (change_set.title, change_set.description) == ("chore: bump", "")


class TestFromRange:
    def test_maps_range_info_with_given_title_and_description(self):
        info = _range_info(("feat: a", "Dev One <d1@x>"), ("fix: b", "Dev Two <d2@x>"))

        change_set = from_range(info, title="PROJ-1 do the thing", description="Why: because")

        assert change_set.kind == "merge_request"
        assert change_set.ref == f"{'b' * 8}..{'h' * 8}"
        assert (change_set.base_sha, change_set.head_sha) == ("b" * 40, "h" * 40)
        assert change_set.title == "PROJ-1 do the thing"
        assert change_set.description == "Why: because"
        assert change_set.authors == ["Dev One <d1@x>", "Dev Two <d2@x>"]
        assert [c.subject for c in change_set.commits] == ["feat: a", "fix: b"]
        assert change_set.commits[1].short_hash == "2" * 8
        assert change_set.date is None

    def test_single_commit_range_falls_back_to_its_subject(self):
        change_set = from_range(_range_info(("feat: only one", "D <d@x>")))

        assert change_set.title == "feat: only one"
        assert change_set.description == ""

    def test_multi_commit_range_falls_back_to_a_count(self):
        info = _range_info(("feat: a", "D <d@x>"), ("fix: b", "D <d@x>"), ("test: c", "D <d@x>"))

        change_set = from_range(info)

        assert change_set.title == f"3 commits ({'b' * 8}..{'h' * 8})"

    def test_blank_title_falls_back_too(self):
        change_set = from_range(_range_info(("feat: x", "D <d@x>")), title="   ")

        assert change_set.title == "feat: x"

    def test_empty_range_is_rejected(self):
        with pytest.raises(ValueError, match="no commits"):
            from_range(_range_info())


class TestGitlabMrContext:
    MR_ENV = {
        "CI_MERGE_REQUEST_DIFF_BASE_SHA": "b" * 40,
        "CI_COMMIT_SHA": "h" * 40,
        "CI_MERGE_REQUEST_TITLE": "fix(platform): PROJ-1 thing",
        "CI_MERGE_REQUEST_DESCRIPTION": "What/why/how",
    }

    def test_reads_base_head_title_description(self):
        context = gitlab_mr_context(self.MR_ENV)

        assert context == {
            "base": "b" * 40,
            "head": "h" * 40,
            "title": "fix(platform): PROJ-1 thing",
            "description": "What/why/how",
        }

    def test_outside_mr_pipeline_is_a_clear_error(self):
        env = {k: v for k, v in self.MR_ENV.items() if k != "CI_MERGE_REQUEST_DIFF_BASE_SHA"}

        with pytest.raises(ValueError, match="merge request pipeline"):
            gitlab_mr_context(env)

    def test_missing_head_is_a_clear_error(self):
        env = {k: v for k, v in self.MR_ENV.items() if k != "CI_COMMIT_SHA"}

        with pytest.raises(ValueError, match="CI_COMMIT_SHA"):
            gitlab_mr_context(env)

    def test_title_and_description_are_optional(self):
        env = {
            "CI_MERGE_REQUEST_DIFF_BASE_SHA": "b" * 40,
            "CI_COMMIT_SHA": "h" * 40,
        }

        context = gitlab_mr_context(env)

        assert (context["title"], context["description"]) == (None, "")

    def test_truncated_description_is_marked(self):
        env = {**self.MR_ENV, "CI_MERGE_REQUEST_DESCRIPTION_IS_TRUNCATED": "true"}

        context = gitlab_mr_context(env)

        assert context["description"] == "What/why/how\n\n[description truncated by GitLab]"

    def test_not_truncated_flag_leaves_description_alone(self):
        env = {**self.MR_ENV, "CI_MERGE_REQUEST_DESCRIPTION_IS_TRUNCATED": "false"}

        assert gitlab_mr_context(env)["description"] == "What/why/how"
