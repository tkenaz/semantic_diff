"""
Files the review tools never read: where secrets live by convention.

Redaction erases what it recognises; this keeps whole files out of reach
whether or not their contents look like a secret, so the redactor is a
second layer, not the only one. A changed file of this kind still reaches
the model through its diff, erased like every other diff.

A pattern without "/" matches the file name in any directory; one with "/"
matches the whole path from the repository root (fnmatch: * crosses "/").
"""

from fnmatch import fnmatchcase
from typing import Iterable, Tuple

DEFAULT_WITHHELD: Tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    "credentials",
    "credentials.*",
    "*.tfvars",
    "*.tfstate",
    "*.tfstate.*",
    "secrets/*",
    "*/secrets/*",
)


class WithheldPaths:
    def __init__(self, patterns: Iterable[str] = DEFAULT_WITHHELD):
        self.patterns = tuple(patterns)

    def __call__(self, path: str) -> bool:
        name = path.rsplit("/", 1)[-1]
        return any(
            fnmatchcase(path if "/" in pattern else name, pattern) for pattern in self.patterns
        )
