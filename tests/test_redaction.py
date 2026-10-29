"""
Tests for redaction: nothing the review sends to a model carries a secret
written in the repository - not the diff, the title, the description, the
commit subjects, nor what read_file, read_base, grep and git_log return -
and line numbers still hold for citations.
"""

from unittest.mock import patch

import pytest
from click.testing import CliRunner
from git import Repo

from semantic_diff.cli import main
from semantic_diff.models import ChangeSet, CommitRef, FileChange
from semantic_diff.redaction import Redactor
from semantic_diff.review.tools import Toolbox
from tests.conftest import _commit
from tests.test_review_agent import ScriptedProvider, call, submit, uses

# Assembled at runtime so secret scanners on the repository host stay quiet
IN_CONFIG = "q8Zr3" + "Kx9Lm2Vb7Tn4Yw1Pc6Hs5Jd0Fg"
IN_DIFF = "Zq81kLm0" + "9xPw7Rt3Yv"
IN_SUBJECT = "sk-ant-" + "api03-fixture0000000000000000"
PEM = "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEow\nAAAA\n-----END RSA " + "PRIVATE KEY-----"


@pytest.fixture
def secret_repo(tmp_path):
    """base: config.py holds a key; feature: adds one to .env, commit subject leaks a third"""
    repo = Repo.init(tmp_path)
    base = _commit(
        repo,
        tmp_path,
        {"config.py": f'API_TOKEN = "{IN_CONFIG}"\n', "api.py": "def get():\n    return 1\n"},
        "base",
    )
    repo.create_head("target", base)
    repo.create_head("feature", base).checkout()
    head = _commit(
        repo,
        tmp_path,
        {".env": f"SERVICE_TOKEN={IN_DIFF}\n", "api.py": "def get():\n    return 2\n"},
        f"feat: wire {IN_SUBJECT}",
    )
    return {"path": str(tmp_path), "repo": repo, "base": base, "head": head}


def _secrets_in(text: str):
    return [s for s in (IN_CONFIG, IN_DIFF, IN_SUBJECT) if s in text]


class TestReview:
    def _review(self, secret_repo, *extra):
        provider = ScriptedProvider(
            uses(
                call("read_file", {"path": "config.py"}),
                call("read_base", {"path": "config.py"}),
                call("grep", {"pattern": "TOKEN"}),
                call("git_log", {"path": ".env"}),
            ),
            uses(submit()),
        )
        with patch("semantic_diff.cli.build_provider", return_value=provider):
            result = CliRunner().invoke(
                main,
                ["review", "--base", "target", "--head", "feature"]
                + ["--repo", secret_repo["path"], "--json", *extra],
            )
        assert result.exit_code == 0, result.output
        return provider, result

    def test_no_secret_reaches_the_model(self, secret_repo):
        provider, result = self._review(secret_repo)

        sent = repr(provider.requests)
        assert _secrets_in(sent) == []
        assert "[SECRET_" in sent
        assert '"redacted": ' in result.stdout and '"redacted": 0' not in result.stdout

    def test_without_redaction_the_model_sees_them(self, secret_repo):
        provider, result = self._review(secret_repo, "--no-redact")

        assert set(_secrets_in(repr(provider.requests))) == {IN_CONFIG, IN_DIFF, IN_SUBJECT}
        assert '"redacted": null' in result.stdout


class TestToolbox:
    @pytest.fixture
    def toolbox(self, secret_repo):
        return Toolbox(
            secret_repo["repo"],
            head=secret_repo["head"].hexsha,
            base=secret_repo["base"].hexsha,
            redactor=Redactor(),
        )

    def test_grep_keeps_path_and_line_number(self, toolbox):
        out = toolbox.grep("TOKEN")

        assert ".env:1:SERVICE_TOKEN=[SECRET_" in out
        assert 'config.py:1:API_TOKEN = "[SECRET_' in out

    def test_the_same_value_gets_the_same_placeholder_everywhere(self, toolbox):
        first = toolbox.read_file("config.py")
        again = toolbox.read_base("config.py")

        assert first.splitlines()[1] == again.splitlines()[1]


class TestRedactor:
    def test_a_private_key_keeps_the_file_line_count(self):
        text = f"a\n{PEM}\nb"

        assert len(Redactor().lines(text)) == len(text.splitlines())

    def test_change_erases_title_description_subjects_and_diffs(self):
        change_set = ChangeSet(
            kind="merge_request",
            ref="a..b",
            head_sha="b" * 40,
            title=f"use {IN_SUBJECT}",
            description=f"token: {IN_SUBJECT}",
            commits=[CommitRef(short_hash="b", subject=f"add {IN_SUBJECT}", author="x")],
        )
        diff = f"@@ -0,0 +1,2 @@\n+SERVICE_TOKEN={IN_DIFF}\n+x = 1\n"
        files = [FileChange(path=".env", change_type="added", diff_content=diff)]
        redactor = Redactor()

        erased_set, [erased] = redactor.change(change_set, files)

        assert _secrets_in(erased_set.model_dump_json() + erased.diff_content) == []
        assert erased.diff_content.count("\n") == diff.count("\n")
        assert redactor.erased == 4

    def test_empty_text_costs_nothing(self):
        redactor = Redactor()

        assert redactor("") == ""
        assert redactor.erased == 0
