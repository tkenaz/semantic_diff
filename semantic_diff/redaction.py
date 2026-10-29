"""
Secrets and personal data out of everything the reviewer sends to a model:
the diff, the title and description, commit subjects, and what the tools read.

One pii-eraser session for the whole review, so a value gets the same
placeholder wherever it appears: the model can still see that the key in
the diff is the key in config.py. Placeholders are never restored: the
report and the MR comment keep them too.
"""

from typing import List, Tuple

from pii_eraser import Eraser

from semantic_diff.models import ChangeSet, FileChange


class Redactor:
    def __init__(self):
        self._session = Eraser.for_code().session()
        self.erased = 0  # values replaced, over all texts

    def __call__(self, text: str) -> str:
        erased, count = self._erase(text)
        self.erased += count
        return erased

    def _erase(self, text: str) -> Tuple[str, int]:
        if not text:
            return text, 0
        result = self._session.erase(text)
        return result.text, len(result.found)

    def lines(self, text: str) -> List[str]:
        """Erase a whole file, then split: a private key block spans lines.
        Line numbers must hold for citations; a rule that swallowed a line
        break falls back to erasing line by line."""
        lines = text.splitlines()
        whole, count = self._erase(text)
        if len(whole.splitlines()) == len(lines):
            self.erased += count
            return whole.splitlines()
        return [self(line) for line in lines]

    def keeping_lines(self, text: str) -> str:
        """Same, for a diff: diffs are split on \\n alone, and a \\r or \\u2028
        inside a line must not become a line of its own."""
        whole, count = self._erase(text)
        if whole.count("\n") == text.count("\n"):
            self.erased += count
            return whole
        return "\n".join(self(part) for part in text.split("\n"))

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
        erased_files = [
            f.model_copy(update={"diff_content": self.keeping_lines(f.diff_content)}) for f in files
        ]
        return erased_set, erased_files
