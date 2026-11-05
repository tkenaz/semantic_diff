"""
Path patterns for repository files, one syntax wherever a CLI option takes globs.

A pattern without "/" matches the file name in any directory; one with "/"
matches the whole path from the repository root (fnmatch: * crosses "/").
A leading "**/" also matches at the root: "**/fixtures/**" covers
"fixtures/a.json" as well as "tests/fixtures/a.json".
"""

from fnmatch import fnmatchcase
from typing import Iterable


def matches(path: str, pattern: str) -> bool:
    if "/" not in pattern:
        return fnmatchcase(path.rsplit("/", 1)[-1], pattern)
    if fnmatchcase(path, pattern):
        return True
    return pattern.startswith("**/") and matches(path, pattern[3:])


class PathGlobs:
    def __init__(self, patterns: Iterable[str] = ()):
        self.patterns = tuple(patterns)

    def __call__(self, path: str) -> bool:
        return any(matches(path, pattern) for pattern in self.patterns)
