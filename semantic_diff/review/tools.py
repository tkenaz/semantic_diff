"""
Read-only tools the review agent calls to look around the change.

Everything is read from git objects at the merge request's head and base SHAs,
never from the working tree: a review is reproducible, and nothing that is not
committed (local secrets, build output) can reach the model. Output is capped
per call; a cap always says how to get the rest.
"""

import inspect
from pathlib import PurePosixPath
from typing import Any, Optional, Tuple

from git import GitCommandError, Repo

from semantic_diff.providers import ToolCall, ToolResult, ToolSpec

LINE_CUT = 300


class ToolError(Exception):
    """A tool call the model got wrong; the message goes back to the model."""


def _path_arg(description: str) -> dict:
    return {"type": "string", "description": description}


def _object_schema(properties: dict, required: Tuple[str, ...] = ()) -> dict:
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    return schema


LINE_RANGE = {
    "start_line": {"type": "integer", "description": "First line, 1-based (default 1)"},
    "end_line": {"type": "integer", "description": "Last line, inclusive (default: a page)"},
}

SPECS = (
    ToolSpec(
        "read_file",
        "Read a file as it is AFTER the change (at the merge request head), with line numbers.",
        _object_schema(
            {"path": _path_arg("Path from the repository root"), **LINE_RANGE}, ("path",)
        ),
    ),
    ToolSpec(
        "read_base",
        "Read a file as it was BEFORE the change (at the merge base), with line numbers.",
        _object_schema(
            {"path": _path_arg("Path from the repository root"), **LINE_RANGE}, ("path",)
        ),
    ),
    ToolSpec(
        "grep",
        "Search all files after the change with an extended regular expression. "
        "Returns path:line:text. Use it to find callers, other usages and config.",
        _object_schema(
            {
                "pattern": {"type": "string", "description": "Extended regex (git grep -E)"},
                "path_glob": {"type": "string", "description": "Limit to paths, e.g. '*.ts'"},
                "ignore_case": {"type": "boolean"},
            },
            ("pattern",),
        ),
    ),
    ToolSpec(
        "list_dir",
        "List a directory after the change; subdirectories end with '/'.",
        _object_schema({"path": _path_arg("Directory; empty for the repository root")}),
    ),
    ToolSpec(
        "git_log",
        "Recent commits touching a path, up to the merge request head.",
        _object_schema(
            {
                "path": _path_arg("File or directory"),
                "limit": {"type": "integer", "description": "1-30, default 10"},
            },
            ("path",),
        ),
    ),
)


class Toolbox:
    def __init__(
        self,
        repo: Repo,
        *,
        head: str,
        base: str,
        max_lines: int = 400,
        max_chars: int = 40_000,
        max_matches: int = 100,
        max_entries: int = 300,
        git_timeout: float = 20.0,
    ):
        self.repo = repo
        self.head = head
        self.base = base
        self.max_lines = max_lines
        self.max_chars = max_chars
        self.max_matches = max_matches
        self.max_entries = max_entries
        self.git_timeout = git_timeout

    @property
    def specs(self) -> Tuple[ToolSpec, ...]:
        return SPECS

    def run(self, call: ToolCall) -> ToolResult:
        names = [s.name for s in SPECS]
        if call.name not in names:
            return _error(call, f"unknown tool {call.name}; available: {', '.join(names)}")
        if call.arguments is None:
            return _error(call, f"arguments must be a JSON object, got: {call.raw_arguments}")
        method = getattr(self, call.name)
        try:
            inspect.signature(method).bind(**call.arguments)
        except TypeError as e:
            return _error(call, f"bad arguments for {call.name}: {e}")
        try:
            return ToolResult(call.id, method(**call.arguments))
        except ToolError as e:
            return _error(call, str(e))

    # --- tools ---------------------------------------------------------------

    def read_file(
        self, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None
    ) -> str:
        return self._read("head", self.head, path, start_line, end_line)

    def read_base(
        self, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None
    ) -> str:
        return self._read("base", self.base, path, start_line, end_line)

    def grep(
        self, pattern: str, path_glob: Optional[str] = None, ignore_case: Optional[bool] = None
    ) -> str:
        pattern = _string("pattern", pattern)
        if not pattern:
            raise ToolError("pattern must not be empty")
        args = ["-n", "-I", "--no-color", "-E"]
        if _flag("ignore_case", ignore_case):
            args.append("-i")
        # -e: a pattern like "--force" must not be read as an option
        args += ["-e", pattern, self.head, "--"]
        if path_glob is not None:
            args.append(_string("path_glob", path_glob))
        try:
            out = self.repo.git.grep(*args, kill_after_timeout=self.git_timeout)
        except GitCommandError as e:
            if e.status == 1:
                return "no matches"
            # GitPython renders stderr as "  stderr: '<text>'"
            stderr = str(e.stderr).strip().removeprefix("stderr: ").strip("'")
            raise ToolError(f"grep failed: {stderr}") from e

        prefix = f"{self.head}:"
        matches = [_cut(line.removeprefix(prefix)) for line in out.splitlines()]
        shown = matches[: self.max_matches]
        if len(shown) < len(matches):
            shown.append(
                f"[{len(shown)} of {len(matches)} matches shown; narrow the pattern or path_glob]"
            )
        return "\n".join(shown)

    def list_dir(self, path: str = "") -> str:
        path = _clean_path(_string("path", path), allow_root=True)
        tree = self._object("head", self.head, path)
        if tree.type != "tree":
            raise ToolError(f"{path} is not a directory")
        entries = sorted(f"{item.name}/" if item.type == "tree" else item.name for item in tree)
        shown = entries[: self.max_entries]
        if len(shown) < len(entries):
            shown.append(f"[{len(shown)} of {len(entries)} entries shown]")
        return "\n".join(shown)

    def git_log(self, path: str, limit: Optional[int] = None) -> str:
        path = _clean_path(_string("path", path))
        limit = _integer("limit", limit, default=10)
        if not 1 <= limit <= 30:
            raise ToolError("limit must be between 1 and 30")
        out = self.repo.git.log(
            self.head,
            f"-n{limit}",
            "--format=%h %ad %an: %s",
            "--date=short",
            "--",
            path,
            kill_after_timeout=self.git_timeout,
        )
        return out or f"no commits touch {path}"

    # --- helpers -------------------------------------------------------------

    def _object(self, side: str, sha: str, path: str):
        tree = self.repo.commit(sha).tree
        if not path:
            return tree
        try:
            return tree[path]
        except KeyError:
            raise ToolError(f"{path} does not exist at {side}") from None

    def _read(
        self,
        side: str,
        sha: str,
        path: str,
        start_line: Optional[int],
        end_line: Optional[int],
    ) -> str:
        path = _clean_path(_string("path", path))
        start = _integer("start_line", start_line, default=1)
        end = _integer("end_line", end_line, default=None)
        if start < 1:
            raise ToolError("start_line must be at least 1")
        if end is not None and end < start:
            raise ToolError("end_line must not be before start_line")

        blob = self._object(side, sha, path)
        if blob.type == "tree":
            raise ToolError(f"{path} is a directory; use list_dir")
        data = blob.data_stream.read()
        if b"\0" in data[:8000]:
            raise ToolError(f"{path} is a binary file")
        lines = data.decode("utf-8", errors="replace").splitlines()
        total = len(lines)
        if total == 0:
            return f"{path} ({side}) is empty"
        if start > total:
            raise ToolError(f"{path} has {total} lines; start_line {start} is past the end")

        wanted = min(total, end or total)
        rows = []
        size = 0
        for number in range(start, min(wanted, start + self.max_lines - 1) + 1):
            row = f"{number:>5}| {lines[number - 1]}"
            if rows and size + len(row) + 1 > self.max_chars:
                break
            rows.append(row)
            size += len(row) + 1

        stop = start + len(rows) - 1
        out = [f"{path} ({side}) lines {start}-{stop} of {total}", *rows]
        if stop < wanted:
            out.append(f"[more: continue with start_line={stop + 1}]")
        return "\n".join(out)


def _error(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call.id, message, is_error=True)


def _clean_path(path: str, *, allow_root: bool = False) -> str:
    clean = path.strip().removeprefix("./").rstrip("/")
    if clean in ("", "."):
        if allow_root:
            return ""
        raise ToolError("path must name a file in the repository")
    if clean.startswith("/") or ".." in PurePosixPath(clean).parts:
        raise ToolError(f"path must be relative to the repository root, without '..': {path}")
    return clean


def _string(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ToolError(f"{name} must be a string")
    return value


def _integer(name: str, value: Any, *, default):
    if value is None:
        return default
    # bool is an int subclass; true/false is never a line number
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolError(f"{name} must be an integer")
    return value


def _flag(name: str, value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ToolError(f"{name} must be a boolean")
    return value


def _cut(match: str) -> str:
    path, number, text = match.split(":", 2)
    if len(text) > LINE_CUT:
        text = text[:LINE_CUT] + " [line cut]"
    return f"{path}:{number}:{text}"
