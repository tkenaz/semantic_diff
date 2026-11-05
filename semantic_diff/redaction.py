"""
Secrets and personal data out of everything the reviewer sends to a model:
the diff, the title and description, commit subjects, and what the tools read.

One pii-eraser session for the whole review, so a value gets the same
placeholder wherever it appears: the model can still see that the key in
the diff is the key in config.py. Placeholders are never restored: the
report and the MR comment keep them too.

Two things are not personal data and stay as written:
- addresses on names reserved for documentation and testing (RFC 2606 and
  RFC 6761: example.com/.net/.org, *.test, *.example, *.invalid, localhost),
  always;
- personal data in files matched by pii_exempt (e.g. tests/**): synthetic
  fixtures. Secrets there are still erased - a real key committed to a test
  is still a real key - and so is any value already erased elsewhere.
"""

from typing import Callable, List, Optional, Tuple

from pii_eraser import Eraser, Kind, Span
from pii_eraser.eraser import resolve_overlaps
from pii_eraser.session import Session

from semantic_diff.models import ChangeSet, FileChange

RESERVED_DOMAINS = ("example.com", "example.net", "example.org")
RESERVED_TLDS = ("test", "example", "invalid", "localhost")


def is_reserved_domain(domain: str) -> bool:
    """True for a name that can never belong to a real person (RFC 2606, RFC 6761)."""
    domain = domain.strip().rstrip(".").lower()
    return any(
        domain == name or domain.endswith("." + name) for name in RESERVED_DOMAINS + RESERVED_TLDS
    )


def _synthetic(span: Span) -> bool:
    return span.kind is Kind.EMAIL and is_reserved_domain(span.text.rpartition("@")[2])


class Redactor:
    def __init__(self, pii_exempt: Optional[Callable[[str], bool]] = None):
        # The code profile's stages, run here rather than through Eraser.detect:
        # synthetic spans are dropped before overlaps are resolved, so a dropped
        # email can never have pushed out the password it overlapped
        self._stages = [stage for stage in Eraser.for_code().stages if stage.replace]
        self._session = Session()
        self._pii_exempt = pii_exempt or (lambda path: False)
        self.erased = 0  # values replaced, over all texts

    def __call__(self, text: str, path: Optional[str] = None) -> str:
        erased, count = self._erase(text, path)
        self.erased += count
        return erased

    def _erase(self, text: str, path: Optional[str] = None) -> Tuple[str, int]:
        if not text:
            return text, 0
        secrets_only = path is not None and self._pii_exempt(path)
        found = resolve_overlaps(
            [
                span
                for stage in self._stages
                for span in stage.detector.detect(text)
                if span.confidence >= stage.min_confidence and self._erases(span, secrets_only)
            ]
        )
        return self._session.apply(text, found), len(found)

    @staticmethod
    def _erases(span: Span, secrets_only: bool) -> bool:
        if span.kind is Kind.SECRET:
            return True
        return not secrets_only and not _synthetic(span)

    def lines(self, text: str, path: Optional[str] = None) -> List[str]:
        """Erase a whole file, then split: a private key block spans lines.
        Line numbers must hold for citations; a rule that swallowed a line
        break falls back to erasing line by line."""
        lines = text.splitlines()
        whole, count = self._erase(text, path)
        if len(whole.splitlines()) == len(lines):
            self.erased += count
            return whole.splitlines()
        return [self(line, path) for line in lines]

    def keeping_lines(self, text: str, path: Optional[str] = None) -> str:
        """Same, for a diff: diffs are split on \\n alone, and a \\r or \\u2028
        inside a line must not become a line of its own."""
        whole, count = self._erase(text, path)
        if whole.count("\n") == text.count("\n"):
            self.erased += count
            return whole
        return "\n".join(self(part, path) for part in text.split("\n"))

    def change(
        self, change_set: ChangeSet, files: List[FileChange]
    ) -> Tuple[ChangeSet, List[FileChange]]:
        commits = [c.model_copy(update={"subject": self(c.subject)}) for c in change_set.commits]
        erased_set = change_set.model_copy(
            update={
                "title": self(change_set.title),
                "description": self(change_set.description),
                "commits": commits,
            }
        )
        # Exempt files last: a value found in code is then erased in fixtures too,
        # whatever order the diff lists them in
        erased_files = list(files)
        for i in sorted(range(len(files)), key=lambda i: self._pii_exempt(files[i].path)):
            f = files[i]
            erased_files[i] = f.model_copy(
                update={"diff_content": self.keeping_lines(f.diff_content, f.path)}
            )
        return erased_set, erased_files
