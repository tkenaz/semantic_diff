"""
Prompt pieces shared by the one-shot analyzer and the review agent. Pure text
rendering; author-provided text is fenced as untrusted.
"""

import re
from typing import Iterator, List, Optional, Tuple

from semantic_diff.diff_pack import DiffPack
from semantic_diff.models import ChangeSet, FileChange

MAX_DESCRIPTION_CHARS = 4000

# Any spelling of our fence tag inside author text: the description must not
# be able to close its own fence and continue as trusted prompt text
FENCE_TAG = re.compile(r"<\s*/?\s*untrusted_description\s*>", re.IGNORECASE)


def format_change_set(change_set: ChangeSet) -> str:
    """The change under review; the description is fenced as untrusted"""
    kind = "merge request" if change_set.kind == "merge_request" else "commit"
    lines = [
        f"- **Type:** {kind}",
        f"- **Ref:** {change_set.ref}",
        f"- **Title:** {change_set.title}",
    ]
    if change_set.authors:
        lines.append(f"- **Authors:** {', '.join(change_set.authors)}")
    if change_set.date:
        lines.append(f"- **Date:** {change_set.date}")

    if change_set.description:
        description = FENCE_TAG.sub("[fence tag removed]", change_set.description)
        if len(description) > MAX_DESCRIPTION_CHARS:
            description = description[:MAX_DESCRIPTION_CHARS] + "\n[description truncated]"
        lines += [
            "",
            "### Description (author-provided)",
            "<untrusted_description>",
            description,
            "</untrusted_description>",
        ]

    if change_set.kind == "merge_request":
        lines += ["", "### Commits (oldest first)"]
        lines += [f"- {c.short_hash} {c.subject} ({c.author})" for c in change_set.commits]

    return "\n".join(lines)


def format_files_summary(files: List[FileChange]) -> str:
    """Every changed file with its size, shown or not"""
    lines = []
    for f in files:
        lang = f"[{f.language}]" if f.language else ""
        lines.append(f"- {f.path} ({f.change_type}) +{f.additions}/-{f.deletions} {lang}")
    return "\n".join(lines)


def format_diffs(packed: DiffPack, numbered: bool = False) -> str:
    """Render the packed diffs and name every file the model will not see"""
    blocks = []
    for shown in packed.shown:
        header = f"### {shown.file.path} ({shown.file.change_type})"
        if shown.trimmed:
            header += f" - {shown.hunks_shown} of {shown.hunks_total} hunks shown"
        text = number_lines(shown.text) if numbered else shown.text
        fence = fence_for(text)
        blocks.append(f"{header}\n{fence}diff\n{text}\n{fence}")

    coverage = packed.coverage
    not_shown = [f"- {path} (over the diff budget)" for path in coverage.omitted]
    not_shown += [f"- {path} (lock/generated/binary)" for path in coverage.noise]
    if not_shown:
        blocks.append("### Not shown\n" + "\n".join(not_shown))

    return "\n\n".join(blocks)


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def diff_lines(diff: str) -> Iterator[Tuple[str, Optional[str]]]:
    """
    Each diff line with the number it is shown under: "42" after the change
    (context and added lines), "b17" before it (removed ones), "" for a
    "\\ No newline" marker inside a hunk, None outside any hunk.
    """
    old = new = None
    for line in diff.split("\n"):
        header = HUNK_HEADER.match(line)
        if header:
            old, new = int(header.group(1)), int(header.group(2))
            yield line, None
        elif new is None:
            yield line, None
        elif line.startswith("\\"):
            yield line, ""
        elif line.startswith("-"):
            yield line, f"b{old}"
            old += 1
        elif line.startswith("+"):
            yield line, str(new)
            new += 1
        else:
            yield line, str(new)
            old += 1
            new += 1


def number_lines(diff: str) -> str:
    """
    Prefix diff lines with their line number: after the change for context and
    added lines, "b<N>" (before the change) for removed ones. Rendered after
    packing, so the budget does not count the prefixes.
    """
    out = []
    for line, number in diff_lines(diff):
        if number is None:
            out.append(line)
        elif not number:
            out.append(f"{'':>6}{line}")
        else:
            out.append(f"{number:>5}|{line}")
    return "\n".join(out)


def fence_for(text: str) -> str:
    # A fence longer than any backtick run inside keeps the diff from closing it
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)
