"""
Tests for GitParser range mode - analyzing a merge request (base..head)
instead of a single commit.

Semantics mirror GitLab's MR "Changes" tab: three-dot diff from the merge
base of target and source to the source head.
"""

import pytest

from semantic_diff.parsers.git_parser import GitParser
from tests.conftest import AUTHOR, _commit


class TestGetRangeChanges:
    def test_includes_changes_from_every_commit_in_range(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        assert sorted(c.path for c in changes) == ["api.py", "util.py"]

    def test_excludes_changes_made_on_target_after_branch_point(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        assert "docs.md" not in [c.path for c in changes]

    def test_diffs_against_merge_base_not_against_target_tip(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        api = next(c for c in changes if c.path == "api.py")
        assert api.change_type == "modified"
        assert "-    return 1" in api.diff_content
        assert "+    return 3" in api.diff_content
        assert "return 2" not in api.diff_content
        assert (api.additions, api.deletions) == (1, 1)

    def test_added_file_in_range(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        util = next(c for c in changes if c.path == "util.py")
        assert util.change_type == "added"
        assert util.language == "python"
        assert util.additions == 1

    def test_change_reverted_within_range_is_absent(self, mr_repo, tmp_path):
        repo = mr_repo["repo"]
        repo.heads.feature.checkout()
        _commit(repo, tmp_path, {"docs.md": "temp\n"}, "wip")
        head = _commit(repo, tmp_path, {"docs.md": "v1\n"}, "revert wip")
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["target_tip"].hexsha, head.hexsha)

        assert "docs.md" not in [c.path for c in changes]

    def test_deleted_file_in_range(self, mr_repo, tmp_path):
        repo = mr_repo["repo"]
        repo.heads.feature.checkout()
        head = _commit(repo, tmp_path, {}, "drop docs", remove=["docs.md"])
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["target_tip"].hexsha, head.hexsha)

        docs = next(c for c in changes if c.path == "docs.md")
        assert docs.change_type == "deleted"
        assert docs.deletions == 1

    def test_renamed_file_in_range_is_detected(self, mr_repo, tmp_path):
        repo = mr_repo["repo"]
        repo.heads.feature.checkout()
        (tmp_path / "models.py").rename(tmp_path / "schema.py")
        repo.index.remove(["models.py"])
        repo.index.add(["schema.py"])
        head = repo.index.commit("rename models", author=AUTHOR, committer=AUTHOR)
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["target_tip"].hexsha, head.hexsha)

        renamed = [c for c in changes if c.change_type == "renamed"]
        assert [c.path for c in renamed] == ["models.py -> schema.py"]
        assert renamed[0].language == "python"

    def test_unknown_base_raises_clear_error(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        with pytest.raises(ValueError, match="Could not find commit: deadbeef"):
            parser.get_range_changes("deadbeef", mr_repo["head"].hexsha)

    def test_unrelated_histories_raise_clear_error(self, mr_repo, tmp_path):
        repo = mr_repo["repo"]
        repo.git.checkout("--orphan", "island")
        repo.git.rm("-rf", "--cached", ".")
        island = _commit(repo, tmp_path, {"lonely.txt": "x\n"}, "island")
        parser = GitParser(mr_repo["path"])

        with pytest.raises(ValueError, match="No common ancestor"):
            parser.get_range_changes(island.hexsha, mr_repo["head"].hexsha)


class TestGetRangeInfo:
    def test_lists_commits_oldest_first_excluding_target(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        info = parser.get_range_info(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        assert [c["subject"] for c in info["commits"]] == [
            "feat: return 2",
            "feat: add util",
            "fix: return 3",
        ]

    def test_commit_entries_carry_short_hash_and_author(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        info = parser.get_range_info(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        c2 = info["commits"][1]
        assert c2["short_hash"] == mr_repo["commits"][1].hexsha[:8]
        assert c2["author"] == "Dev Two <dev2@example.com>"

    def test_reports_merge_base_and_head(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        info = parser.get_range_info(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        assert info["merge_base"] == mr_repo["base"].hexsha
        assert info["head"] == mr_repo["head"].hexsha
        assert info["short_range"] == f"{mr_repo['base'].hexsha[:8]}..{mr_repo['head'].hexsha[:8]}"

    def test_authors_are_unique_in_first_seen_order(self, mr_repo):
        parser = GitParser(mr_repo["path"])

        info = parser.get_range_info(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        assert info["authors"] == ["Dev One <dev1@example.com>", "Dev Two <dev2@example.com>"]


class TestRangeRobustness:
    def test_rename_detected_even_when_git_config_disables_renames(self, mr_repo, tmp_path):
        repo = mr_repo["repo"]
        with repo.config_writer() as config:
            config.set_value("diff", "renames", "false")
        repo.heads.feature.checkout()
        (tmp_path / "models.py").rename(tmp_path / "schema.py")
        repo.index.remove(["models.py"])
        repo.index.add(["schema.py"])
        head = repo.index.commit("rename models", author=AUTHOR, committer=AUTHOR)
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["target_tip"].hexsha, head.hexsha)

        assert "models.py -> schema.py" in [c.path for c in changes]

    def test_result_does_not_depend_on_checked_out_branch(self, mr_repo):
        mr_repo["repo"].heads.feature.checkout()
        parser = GitParser(mr_repo["path"])

        info = parser.get_range_info(mr_repo["target_tip"].hexsha, mr_repo["head"].hexsha)

        assert len(info["commits"]) == 3
        assert info["commits"][0]["hash"] == mr_repo["commits"][0].hexsha

    def test_lines_that_start_with_double_sign_are_counted(self, mr_repo, tmp_path):
        repo = mr_repo["repo"]
        repo.heads.feature.checkout()
        _commit(repo, tmp_path, {"loop.c": "int i;\n--i;\n"}, "add loop")
        head = _commit(repo, tmp_path, {"loop.c": "int i;\n++i;\n"}, "flip loop")
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["commits"][2].hexsha, head.hexsha)

        loop = next(c for c in changes if c.path == "loop.c")
        assert (loop.additions, loop.deletions) == (2, 0)

    def test_modified_counts_double_sign_deletions(self, mr_repo, tmp_path):
        repo = mr_repo["repo"]
        repo.heads.feature.checkout()
        base = _commit(repo, tmp_path, {"loop.c": "int i;\n--i;\n"}, "add loop")
        head = _commit(repo, tmp_path, {"loop.c": "int i;\n++i;\n"}, "flip loop")
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(base.hexsha, head.hexsha)

        assert [(c.additions, c.deletions) for c in changes] == [(1, 1)]

    def test_non_utf8_text_is_decoded_with_replacement(self, mr_repo, tmp_path):
        repo = mr_repo["repo"]
        repo.heads.feature.checkout()
        (tmp_path / "legacy.txt").write_bytes(b"caf\xe9\n")
        repo.index.add(["legacy.txt"])
        head = repo.index.commit("latin-1 file", author=AUTHOR, committer=AUTHOR)
        parser = GitParser(mr_repo["path"])

        changes = parser.get_range_changes(mr_repo["head"].hexsha, head.hexsha)

        assert "caf�" in changes[0].diff_content
