"""
Tests for the review agent's read-only tools. They read git objects at fixed
SHAs - never the working tree - so a review is reproducible and cannot see or
touch anything outside the change under review.
"""

import re
from unittest.mock import Mock

import pytest
from git import Repo

from semantic_diff.providers import ToolCall, ToolResult
from semantic_diff.review.tools import Toolbox, ToolError
from tests.conftest import _commit

APP_BEFORE = "".join(f"line {i}\n" for i in range(1, 11))
APP_AFTER = APP_BEFORE.replace("line 5\n", "line 5 changed\n")


@pytest.fixture
def repo(tmp_path):
    repo = Repo.init(tmp_path)
    base = _commit(
        repo,
        tmp_path,
        {"src/app.py": APP_BEFORE, "src/gone.py": "old\n", "README.md": "hello\n"},
        "base",
    )
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    repo.index.add(["logo.png"])
    head = _commit(
        repo,
        tmp_path,
        {"src/app.py": APP_AFTER, "src/new.py": "def new():\n    return token\n"},
        "head",
        remove=["src/gone.py"],
    )
    # The branch moves on past the reviewed head; tools must stay at head
    _commit(repo, tmp_path, {"src/app.py": "later\n", "src/later.py": "x\n"}, "later")
    # Working tree drifts after the commit; tools must not see it
    (tmp_path / "src" / "app.py").write_text("uncommitted\n")
    (tmp_path / "scratch.py").write_text("token = 'secret'\n")
    return {"repo": repo, "base": base.hexsha, "head": head.hexsha}


def _tools(repo, **limits) -> Toolbox:
    return Toolbox(repo["repo"], head=repo["head"], base=repo["base"], **limits)


def _call(name, arguments=None, raw="") -> ToolCall:
    return ToolCall(id="t1", name=name, arguments=arguments, raw_arguments=raw)


class TestReadFile:
    def test_numbers_lines_of_the_committed_head_version(self, repo):
        out = _tools(repo).read_file("src/app.py", start_line=4, end_line=6)

        assert out == (
            "src/app.py (head) lines 4-6 of 10\n"
            "    4| line 4\n"
            "    5| line 5 changed\n"
            "    6| line 6"
        )

    def test_whole_file_by_default(self, repo):
        out = _tools(repo).read_file("src/new.py")

        assert out == (
            "src/new.py (head) lines 1-2 of 2\n" "    1| def new():\n" "    2|     return token"
        )

    def test_long_file_is_paged_with_a_pointer_to_the_next_page(self, repo):
        out = _tools(repo, max_lines=3).read_file("src/app.py", start_line=2)

        assert out.splitlines()[0] == "src/app.py (head) lines 2-4 of 10"
        assert out.splitlines()[-1] == "[more: continue with start_line=5]"
        assert len(out.splitlines()) == 5

    def test_explicit_end_beyond_the_page_size_is_still_paged(self, repo):
        out = _tools(repo, max_lines=3).read_file("src/app.py", start_line=1, end_line=10)

        assert out.splitlines()[0] == "src/app.py (head) lines 1-3 of 10"

    def test_end_past_the_file_is_clamped_without_a_more_pointer(self, repo):
        out = _tools(repo).read_file("src/app.py", start_line=9, end_line=99)

        assert out.splitlines() == [
            "src/app.py (head) lines 9-10 of 10",
            "    9| line 9",
            "   10| line 10",
        ]

    def test_character_cap_cuts_at_a_line_boundary(self, repo):
        # Each numbered row is 13 chars + newline: three fit in 50, a fourth would not
        out = _tools(repo, max_chars=50).read_file("src/app.py")

        lines = out.splitlines()
        assert lines[0] == "src/app.py (head) lines 1-3 of 10"
        assert lines[1:4] == ["    1| line 1", "    2| line 2", "    3| line 3"]
        assert lines[-1] == "[more: continue with start_line=4]"

    @pytest.mark.parametrize("cap, rows", [(42, 3), (41, 2)])
    def test_character_cap_counts_each_row_with_its_newline(self, repo, cap, rows):
        out = _tools(repo, max_chars=cap).read_file("src/app.py")

        assert out.splitlines()[0] == f"src/app.py (head) lines 1-{rows} of 10"

    def test_invalid_utf8_is_shown_with_replacement_characters(self, repo, tmp_path):
        (tmp_path / "latin1.txt").write_bytes("caf\xe9\n".encode("latin-1"))
        repo["repo"].index.add(["latin1.txt"])
        head = repo["repo"].index.commit("latin1")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"])

        assert tools.read_file("latin1.txt").endswith("    1| caf\ufffd")

    def test_first_line_longer_than_the_character_cap_is_still_shown(self, repo):
        out = _tools(repo, max_chars=5).read_file("src/app.py")

        assert out.splitlines()[:2] == ["src/app.py (head) lines 1-1 of 10", "    1| line 1"]

    def test_start_past_the_end_is_an_error(self, repo):
        with pytest.raises(ToolError, match="has 10 lines"):
            _tools(repo).read_file("src/app.py", start_line=11)

    @pytest.mark.parametrize(
        "start, end, message",
        [
            (0, None, "start_line must be at least 1"),
            (-1, None, "start_line must be at least 1"),
            (5, 4, "end_line must not be before start_line"),
        ],
    )
    def test_bad_line_range_is_an_error(self, repo, start, end, message):
        with pytest.raises(ToolError) as exc:
            _tools(repo).read_file("src/app.py", start_line=start, end_line=end)

        assert str(exc.value) == message

    def test_missing_file_is_an_error_naming_the_side(self, repo):
        with pytest.raises(ToolError, match="src/gone.py does not exist at head"):
            _tools(repo).read_file("src/gone.py")

    def test_uncommitted_file_is_invisible(self, repo):
        with pytest.raises(ToolError, match="does not exist"):
            _tools(repo).read_file("scratch.py")

    def test_directory_is_an_error_pointing_to_list_dir(self, repo):
        with pytest.raises(ToolError, match="directory.*list_dir"):
            _tools(repo).read_file("src")

    def test_binary_file_is_not_dumped(self, repo):
        with pytest.raises(ToolError, match="binary"):
            _tools(repo).read_file("logo.png")

    def test_empty_file(self, repo, tmp_path):
        head = _commit(repo["repo"], tmp_path, {"empty.py": ""}, "empty")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"])

        assert tools.read_file("empty.py") == "empty.py (head) is empty"

    @pytest.mark.parametrize("path", ["/etc/passwd", "../outside.py", "src/../../x"])
    def test_paths_must_stay_inside_the_repository(self, repo, path):
        with pytest.raises(ToolError, match="path must be relative to the repository root"):
            _tools(repo).read_file(path)

    @pytest.mark.parametrize("path", ["", "  ", ".", "./"])
    def test_file_tools_need_a_file_path(self, repo, path):
        with pytest.raises(ToolError) as exc:
            _tools(repo).read_file(path)

        assert str(exc.value) == "path must name a file in the repository"

    def test_leading_dot_slash_is_accepted(self, repo):
        assert _tools(repo).read_file("./src/new.py").startswith("src/new.py (head)")


class TestReadBase:
    def test_reads_the_file_as_it_was_before_the_change(self, repo):
        out = _tools(repo).read_base("src/app.py", start_line=5, end_line=5)

        assert out == "src/app.py (base) lines 5-5 of 10\n    5| line 5"

    def test_deleted_file_is_readable_at_base(self, repo):
        assert _tools(repo).read_base("src/gone.py").endswith("    1| old")

    def test_added_file_did_not_exist_at_base(self, repo):
        with pytest.raises(ToolError, match="src/new.py does not exist at base"):
            _tools(repo).read_base("src/new.py")


class TestGrep:
    def test_finds_matches_at_head_with_path_and_line(self, repo):
        out = _tools(repo).grep("line [45]")

        assert out.splitlines() == ["src/app.py:4:line 4", "src/app.py:5:line 5 changed"]

    def test_searches_the_reviewed_head_not_the_branch_tip(self, repo):
        assert _tools(repo).grep("later") == "no matches"

    def test_colons_inside_the_matching_line_are_kept(self, repo, tmp_path):
        head = _commit(repo["repo"], tmp_path, {"cfg.yml": "url: http://x:80\n"}, "cfg")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"])

        assert tools.grep("url") == "cfg.yml:1:url: http://x:80"

    def test_ignores_the_working_tree(self, repo):
        assert _tools(repo).grep("token").splitlines() == ["src/new.py:2:    return token"]

    def test_path_glob_narrows_the_search(self, repo):
        assert _tools(repo).grep("e", path_glob="*.md").splitlines() == ["README.md:1:hello"]

    def test_ignore_case(self, repo):
        assert _tools(repo).grep("HELLO") == "no matches"
        assert _tools(repo).grep("HELLO", ignore_case=True) == "README.md:1:hello"

    def test_no_match_is_not_an_error(self, repo):
        assert _tools(repo).grep("nothing-like-this") == "no matches"

    def test_pattern_starting_with_a_dash_is_a_pattern_not_an_option(self, repo, tmp_path):
        head = _commit(repo["repo"], tmp_path, {"flags.txt": "--force\n"}, "flags")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"])

        assert tools.grep("--force") == "flags.txt:1:--force"

    def test_binary_files_are_skipped(self, repo):
        assert _tools(repo).grep("PNG") == "no matches"

    def test_match_count_is_capped_with_the_total(self, repo):
        out = _tools(repo, max_matches=3).grep("line")

        assert out.splitlines()[:3] == [
            "src/app.py:1:line 1",
            "src/app.py:2:line 2",
            "src/app.py:3:line 3",
        ]
        assert out.splitlines()[-1] == "[3 of 10 matches shown; narrow the pattern or path_glob]"

    def test_long_matching_lines_are_cut(self, repo, tmp_path):
        head = _commit(repo["repo"], tmp_path, {"min.js": "x" * 1000 + "\n"}, "minified")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"])

        out = tools.grep("x{200}")

        assert out == "min.js:1:" + "x" * 300 + " [line cut]"

    def test_cut_applies_to_the_text_even_when_it_contains_colons(self, repo, tmp_path):
        head = _commit(repo["repo"], tmp_path, {"long.txt": "z" * 400 + ":1\n"}, "long")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"])

        assert tools.grep("z{200}") == "long.txt:1:" + "z" * 300 + " [line cut]"

    def test_line_of_exactly_the_cut_length_is_whole(self, repo, tmp_path):
        head = _commit(repo["repo"], tmp_path, {"w.txt": "y" * 300 + "\n"}, "w")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"])

        assert tools.grep("y") == "w.txt:1:" + "y" * 300

    def test_invalid_regex_is_an_error_carrying_gits_explanation(self, repo):
        with pytest.raises(ToolError) as exc:
            _tools(repo).grep("(unclosed")

        assert str(exc.value).startswith("grep failed: fatal: ")
        assert "(unclosed" in str(exc.value)
        assert not str(exc.value).endswith("'")

    def test_empty_pattern_is_an_error(self, repo):
        with pytest.raises(ToolError) as exc:
            _tools(repo).grep("")

        assert str(exc.value) == "pattern must not be empty"


class TestListDir:
    def test_lists_entries_at_head_directories_marked(self, repo):
        assert _tools(repo).list_dir("").splitlines() == ["README.md", "logo.png", "src/"]

    def test_subdirectory_at_the_reviewed_head(self, repo):
        assert _tools(repo).list_dir("src").splitlines() == ["app.py", "new.py"]

    def test_trailing_slash_is_accepted(self, repo):
        assert _tools(repo).list_dir("src/") == _tools(repo).list_dir("src")

    def test_dot_is_the_root(self, repo):
        assert _tools(repo).list_dir(".") == _tools(repo).list_dir("")

    def test_file_is_an_error(self, repo):
        with pytest.raises(ToolError, match="not a directory"):
            _tools(repo).list_dir("README.md")

    def test_missing_directory_is_an_error(self, repo):
        with pytest.raises(ToolError) as exc:
            _tools(repo).list_dir("nope")

        assert str(exc.value) == "nope does not exist at head"

    def test_entry_count_is_capped(self, repo, tmp_path):
        head = _commit(repo["repo"], tmp_path, {f"many/f{i}.py": "" for i in range(5)}, "many")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"], max_entries=2)

        assert tools.list_dir("many").splitlines() == ["f0.py", "f1.py", "[2 of 5 entries shown]"]


class TestGitLog:
    def test_history_of_a_path_up_to_the_reviewed_head(self, repo):
        out = _tools(repo).git_log("src/app.py")

        subjects = [line.split(": ", 1)[1] for line in out.splitlines()]
        assert subjects == ["head", "base"]
        assert out.splitlines()[0].startswith(repo["head"][:7])
        assert "Dev One: head" in out
        assert re.match(r"^\w+ \d{4}-\d{2}-\d{2} Dev One: head$", out.splitlines()[0])

    def test_limit(self, repo):
        assert len(_tools(repo).git_log("src/app.py", limit=1).splitlines()) == 1

    def test_default_limit_is_ten_and_thirty_is_allowed(self, repo, tmp_path):
        for i in range(31):
            last = _commit(repo["repo"], tmp_path, {"busy.py": f"{i}\n"}, f"edit {i}")
        tools = Toolbox(repo["repo"], head=last.hexsha, base=repo["base"])

        assert len(tools.git_log("busy.py").splitlines()) == 10
        assert len(tools.git_log("busy.py", limit=30).splitlines()) == 30

    @pytest.mark.parametrize("limit", [0, 31])
    def test_limit_is_bounded(self, repo, limit):
        with pytest.raises(ToolError) as exc:
            _tools(repo).git_log("src/app.py", limit=limit)

        assert str(exc.value) == "limit must be between 1 and 30"

    def test_path_without_history(self, repo):
        assert _tools(repo).git_log("never.py") == "no commits touch never.py"


class TestRun:
    def test_dispatches_a_call_to_its_tool(self, repo):
        result = _tools(repo).run(_call("read_base", {"path": "src/gone.py"}))

        assert result == ToolResult("t1", "src/gone.py (base) lines 1-1 of 1\n    1| old")

    def test_tool_error_becomes_an_error_result_for_the_model(self, repo):
        result = _tools(repo).run(_call("read_file", {"path": "missing.py"}))

        assert result.is_error
        assert "missing.py does not exist at head" in result.content

    def test_unknown_tool_lists_the_available_ones(self, repo):
        result = _tools(repo).run(_call("write_file", {"path": "x"}))

        assert result.is_error
        assert result.content == (
            "unknown tool write_file; available: read_file, read_base, grep, list_dir, git_log"
        )

    def test_unparsable_arguments_are_echoed_back(self, repo):
        result = _tools(repo).run(_call("read_file", None, raw="{path: x"))

        assert result == ToolResult("t1", "arguments must be a JSON object, got: {path: x", True)

    @pytest.mark.parametrize(
        "arguments",
        [{}, {"path": "a.py", "mode": "w"}, {"file": "a.py"}],
    )
    def test_missing_or_unexpected_arguments_are_errors(self, repo, arguments):
        result = _tools(repo).run(_call("read_file", arguments))

        assert result.is_error
        assert result.content.startswith("bad arguments for read_file:")

    @pytest.mark.parametrize(
        "name, arguments, message",
        [
            (
                "read_file",
                {"path": "src/app.py", "start_line": "5"},
                "start_line must be an integer",
            ),
            (
                "read_file",
                {"path": "src/app.py", "start_line": True},
                "start_line must be an integer",
            ),
            ("read_file", {"path": "src/app.py", "end_line": "9"}, "end_line must be an integer"),
            ("read_file", {"path": 7}, "path must be a string"),
            ("read_base", {"path": None}, "path must be a string"),
            ("grep", {"pattern": 1}, "pattern must be a string"),
            ("grep", {"pattern": "x", "ignore_case": "yes"}, "ignore_case must be a boolean"),
            ("grep", {"pattern": "x", "path_glob": 5}, "path_glob must be a string"),
            ("list_dir", {"path": ["src"]}, "path must be a string"),
            ("git_log", {"path": 3}, "path must be a string"),
            ("git_log", {"path": "a", "limit": 2.5}, "limit must be an integer"),
        ],
    )
    def test_wrongly_typed_arguments_are_errors(self, repo, name, arguments, message):
        result = _tools(repo).run(_call(name, arguments))

        assert result == ToolResult("t1", message, is_error=True)

    def test_optional_null_arguments_mean_default(self, repo):
        result = _tools(repo).run(
            _call("read_file", {"path": "src/new.py", "start_line": None, "end_line": None})
        )

        assert not result.is_error


class TestGitTimeout:
    def test_every_git_subprocess_is_bounded(self, repo):
        git = Mock()
        git.grep.return_value = ""
        git.log.return_value = ""
        fake_repo = Mock(git=git)
        tools = Toolbox(fake_repo, head="h", base="b", git_timeout=7.0)

        tools.grep("x")
        tools.git_log("a.py")

        assert git.grep.call_args.kwargs == {"kill_after_timeout": 7.0}
        assert git.log.call_args.kwargs == {"kill_after_timeout": 7.0}
        assert git.log.call_args.args[0] == "h"


class TestSpecs:
    def test_one_spec_per_tool_with_closed_object_schemas(self, repo):
        specs = _tools(repo).specs

        assert [s.name for s in specs] == ["read_file", "read_base", "grep", "list_dir", "git_log"]
        for spec in specs:
            assert spec.parameters["type"] == "object"
            assert spec.parameters["additionalProperties"] is False
            assert spec.description

    def test_required_arguments_match_the_tool_signatures(self, repo):
        required = {s.name: s.parameters.get("required", []) for s in _tools(repo).specs}

        assert required == {
            "read_file": ["path"],
            "read_base": ["path"],
            "grep": ["pattern"],
            "list_dir": [],
            "git_log": ["path"],
        }


class TestLineCount:
    def test_counts_lines_on_each_side(self, repo):
        tools = _tools(repo)

        assert tools.line_count("head", "src/app.py") == 10
        assert tools.line_count("base", "src/gone.py") == 1

    @pytest.mark.parametrize(
        "side, path",
        [
            ("head", "src/gone.py"),
            ("base", "src/new.py"),
            ("head", "src"),
            ("head", "logo.png"),
            ("head", "../x"),
            ("head", ""),
        ],
    )
    def test_no_count_when_there_is_no_text_file(self, repo, side, path):
        assert _tools(repo).line_count(side, path) is None

    def test_empty_file_has_zero_lines(self, repo, tmp_path):
        head = _commit(repo["repo"], tmp_path, {"empty.py": ""}, "empty")
        tools = Toolbox(repo["repo"], head=head.hexsha, base=repo["base"])

        assert tools.line_count("head", "empty.py") == 0

    def test_side_must_be_head_or_base(self, repo):
        with pytest.raises(KeyError):
            _tools(repo).line_count("HEAD", "src/app.py")
