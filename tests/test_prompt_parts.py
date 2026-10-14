"""
Tests for prompt pieces shared by the analyzer and the review agent - here,
line numbers in shown diffs, so the review agent can cite lines without
re-reading files it has already seen.
"""

from semantic_diff.diff_pack import pack
from semantic_diff.models import FileChange
from semantic_diff.prompt_parts import format_diffs, number_lines


class TestNumberLines:
    def test_context_and_added_lines_carry_their_line_after_the_change(self):
        diff = "@@ -10,3 +10,4 @@\n keep\n+new one\n+new two\n keep too"

        assert number_lines(diff) == (
            "@@ -10,3 +10,4 @@\n"
            "   10| keep\n"
            "   11|+new one\n"
            "   12|+new two\n"
            "   13| keep too"
        )

    def test_removed_lines_carry_their_line_before_the_change(self):
        diff = "@@ -5,3 +5,2 @@\n a\n-gone\n-gone too\n+in\n b"

        assert number_lines(diff) == (
            "@@ -5,3 +5,2 @@\n"
            "    5| a\n"
            "   b6|-gone\n"
            "   b7|-gone too\n"
            "    6|+in\n"
            "    7| b"
        )

    def test_added_lines_do_not_advance_the_before_numbering(self):
        diff = "@@ -1,2 +1,2 @@\n+x\n-y\n z"

        assert number_lines(diff).splitlines()[1:] == ["    1|+x", "   b1|-y", "    2| z"]

    def test_each_hunk_restarts_from_its_header(self):
        diff = "@@ -1 +1 @@\n-a\n+b\n@@ -40,2 +41,2 @@\n x\n-y\n+z"

        assert number_lines(diff).splitlines()[3:] == [
            "@@ -40,2 +41,2 @@",
            "   41| x",
            "  b41|-y",
            "   42|+z",
        ]

    def test_header_with_a_section_heading(self):
        diff = "@@ -7,1 +7,1 @@ def get():\n-    return 1\n+    return 3"

        assert number_lines(diff).splitlines()[1:] == ["   b7|-    return 1", "    7|+    return 3"]

    def test_no_newline_marker_is_not_numbered_and_does_not_count(self):
        diff = "@@ -1 +1,2 @@\n-a\n\\ No newline at end of file\n+a\n+b"

        assert number_lines(diff).splitlines()[1:] == [
            "   b1|-a",
            "      \\ No newline at end of file",
            "    1|+a",
            "    2|+b",
        ]

    def test_text_before_the_first_hunk_is_left_alone(self):
        assert number_lines("Binary files differ\n@@ -1 +1 @@\n x").splitlines() == [
            "Binary files differ",
            "@@ -1 +1 @@",
            "    1| x",
        ]

    def test_new_file(self):
        assert number_lines("@@ -0,0 +1,2 @@\n+a\n+b").splitlines()[1:] == ["    1|+a", "    2|+b"]

    def test_empty_context_line(self):
        assert number_lines("@@ -3,2 +3,2 @@\n\n-x\n+y").splitlines()[1:] == [
            "    3|",
            "   b4|-x",
            "    4|+y",
        ]


class TestFormatDiffsNumbered:
    def _packed(self, diff: str):
        change = FileChange(path="a.py", change_type="modified", diff_content=diff)
        return pack([change], 10_000)

    def test_numbered_on_request(self):
        out = format_diffs(self._packed("@@ -1 +1 @@\n-a\n+b"), numbered=True)

        assert out == "### a.py (modified)\n```diff\n@@ -1 +1 @@\n   b1|-a\n    1|+b\n```"

    def test_plain_by_default(self):
        out = format_diffs(self._packed("@@ -1 +1 @@\n-a\n+b"))

        assert out == "### a.py (modified)\n```diff\n@@ -1 +1 @@\n-a\n+b\n```"

    def test_fence_accounts_for_the_numbered_text(self):
        out = format_diffs(self._packed("@@ -1 +1 @@\n-a\n+```"), numbered=True)

        assert out.splitlines()[1] == "````diff"
