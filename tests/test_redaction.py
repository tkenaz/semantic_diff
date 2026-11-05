"""
Tests for redaction: nothing the review sends to a model carries a secret
written in the repository - not the diff, the title, the description, the
commit subjects, nor what read_file, read_base, grep and git_log return -
and line numbers still hold for citations.
"""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from git import Repo

from semantic_diff.cli import main
from semantic_diff.models import ChangeSet, CommitRef, FileChange
from semantic_diff.path_globs import PathGlobs
from semantic_diff.redaction import Redactor, is_reserved_domain
from semantic_diff.review.tools import Toolbox
from semantic_diff.review.withheld import WithheldPaths
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
            # Redaction on its own: .env would otherwise be withheld unread
            withheld=WithheldPaths(()),
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

    @pytest.mark.parametrize("separator", ["\r", "\u2028", "\x0c"])
    def test_a_diff_keeps_its_lines_whatever_else_breaks_a_line(self, separator):
        diff = f"@@ -1 +1,2 @@\n+a = 1{separator}b\n+SERVICE_TOKEN={IN_DIFF}\n"

        erased = Redactor().keeping_lines(diff)

        assert erased.split("\n")[1] == f"+a = 1{separator}b"
        assert erased.count("\n") == diff.count("\n")
        assert IN_DIFF not in erased

    def test_empty_text_costs_nothing(self):
        redactor = Redactor()

        assert redactor("") == ""
        assert redactor.erased == 0


class TestAnalyzeAndMr:
    """The one-call commands send the diff, title, description and commit
    subjects too, so they erase the same way review does"""

    def _sent(self, secret_repo, mock_mr_analysis, *args):
        with (
            patch("semantic_diff.cli.build_provider"),
            patch("semantic_diff.cli.LLMAnalyzer") as analyzer,
        ):
            analyzer.return_value.analyze.return_value = mock_mr_analysis
            result = CliRunner().invoke(main, [*args, "--repo", secret_repo["path"], "--json"])
        assert result.exit_code == 0, result.output
        change_set, files, _context = analyzer.return_value.analyze.call_args.args
        return change_set.model_dump_json() + "".join(f.diff_content for f in files)

    @pytest.mark.parametrize(
        "command", [["mr", "--base", "target", "--head", "feature"], ["analyze", "feature"]]
    )
    def test_secrets_are_erased(self, secret_repo, mock_mr_analysis, command):
        sent = self._sent(secret_repo, mock_mr_analysis, *command)

        assert _secrets_in(sent) == []
        assert "[SECRET_" in sent

    def test_no_redact_sends_them_as_written(self, secret_repo, mock_mr_analysis):
        sent = self._sent(
            secret_repo,
            mock_mr_analysis,
            "mr",
            "--base",
            "target",
            "--head",
            "feature",
            "--no-redact",
        )

        assert set(_secrets_in(sent)) == {IN_DIFF, IN_SUBJECT}


# Built at runtime like the secrets above; a real-looking person on a real-looking domain
REAL_EMAIL = "jane.doe" + "@acme-corp.de"


class TestReservedNames:
    """Names reserved for documentation and tests (RFC 2606, RFC 6761) belong
    to no one: an address on one is fixture data, never erased."""

    @pytest.mark.parametrize(
        "email",
        [
            "alice@example.com",
            "bob@example.net",
            "carol@example.org",
            "dave@mail.example.com",
            "erin@qa.test",
            "frank@shop.example",
            "grace@nowhere.invalid",
            "heidi@app.localhost",
            "Ivan@EXAMPLE.COM",
        ],
    )
    def test_reserved_addresses_stay_as_written(self, email):
        redactor = Redactor()

        assert redactor(f'owner = "{email}"') == f'owner = "{email}"'
        assert redactor.erased == 0

    @pytest.mark.parametrize(
        "email",
        [
            REAL_EMAIL,
            "mallory@example.com.attacker.io",  # reserved name as a label, not the suffix
            "trent@notexample.com",
            "peggy@testing.io",
        ],
    )
    def test_other_addresses_are_erased(self, email):
        redactor = Redactor()

        assert email not in redactor(f'owner = "{email}"')
        assert redactor.erased == 1

    def test_a_secret_on_a_reserved_host_is_still_erased(self):
        password = "Xk9pLm2" + "Qw7Rt"

        erased = Redactor()(f'DB = "postgres://app:{password}@db.example.com/app"')

        assert password not in erased
        assert "@db.example.com/app" in erased

    @pytest.mark.parametrize(
        "domain, reserved",
        [
            ("localhost", True),
            ("example.com.", True),
            ("test", True),
            ("example.co", False),
            ("mytest", False),
            ("acme.de", False),
        ],
    )
    def test_is_reserved_domain(self, domain, reserved):
        assert is_reserved_domain(domain) is reserved


class TestPiiExemptPaths:
    """Files the user calls synthetic (--pii-exclude) keep their personal data;
    their secrets do not."""

    def _redactor(self, *patterns):
        return Redactor(PathGlobs(patterns))

    def test_personal_data_in_an_excluded_file_stays(self):
        redactor = self._redactor("tests/**")

        assert redactor(f'"{REAL_EMAIL}"', "tests/fixtures/users.py") == f'"{REAL_EMAIL}"'
        assert redactor.erased == 0

    def test_secrets_in_an_excluded_file_are_still_erased(self):
        redactor = self._redactor("tests/**")

        erased = redactor.lines(f"token = '{IN_SUBJECT}'\n", "tests/conftest.py")

        assert IN_SUBJECT not in erased[0]

    def test_files_outside_the_patterns_are_erased_as_before(self):
        redactor = self._redactor("tests/**")

        assert REAL_EMAIL not in redactor(f'"{REAL_EMAIL}"', "src/users.py")

    def test_a_value_erased_elsewhere_stays_erased_in_an_excluded_file(self):
        # one placeholder per value across the review, whatever the file
        redactor = self._redactor("tests/**")
        in_code = redactor(f'"{REAL_EMAIL}"', "src/users.py")

        assert redactor(f'"{REAL_EMAIL}"', "tests/test_users.py") == in_code

    def test_text_without_a_path_is_never_exempt(self):
        # titles, descriptions, commit subjects
        assert REAL_EMAIL not in self._redactor("**")(f"ping {REAL_EMAIL}")

    def test_change_reads_each_diff_with_its_path(self):
        diff = f'@@ -0,0 +1 @@\n+"{REAL_EMAIL}"\n'
        files = [
            FileChange(path="tests/fixtures/u.json", change_type="added", diff_content=diff),
            FileChange(path="app/u.py", change_type="added", diff_content=diff),
        ]
        change_set = ChangeSet(kind="merge_request", ref="a..b", head_sha="b" * 40, title="t")

        _, (fixture, code) = self._redactor("**/fixtures/**").change(change_set, files)

        assert REAL_EMAIL not in code.diff_content
        # erased in app/u.py first, so the known value is replaced here too
        assert "[EMAIL_1]" in fixture.diff_content

    def test_change_keeps_fixture_data_when_only_fixtures_have_it(self):
        diff = f'@@ -0,0 +1 @@\n+"{REAL_EMAIL}"\n'
        files = [FileChange(path="fixtures/u.json", change_type="added", diff_content=diff)]
        change_set = ChangeSet(kind="merge_request", ref="a..b", head_sha="b" * 40, title="t")

        _, (fixture,) = self._redactor("**/fixtures/**").change(change_set, files)

        assert fixture.diff_content == diff


class TestPathGlobs:
    @pytest.mark.parametrize(
        "pattern, path, hit",
        [
            ("tests/**", "tests/a.py", True),
            ("tests/**", "tests/unit/fixtures/a.json", True),
            ("tests/**", "src/tests/a.py", False),
            ("**/fixtures/**", "fixtures/a.json", True),
            ("**/fixtures/**", "pkg/tests/fixtures/a.json", True),
            ("**/fixtures/**", "pkg/fixtures.py", False),
            ("*.json", "deep/dir/data.json", True),
            ("conftest.py", "tests/conftest.py", True),
        ],
    )
    def test_matches(self, pattern, path, hit):
        assert PathGlobs([pattern])(path) is hit


@pytest.fixture
def fixture_repo(tmp_path):
    """feature adds a test fixture and app code, both holding the same kind of data"""
    repo = Repo.init(tmp_path)
    base = _commit(repo, tmp_path, {"app.py": "x = 1\n"}, "base")
    repo.create_head("target", base)
    repo.create_head("feature", base).checkout()
    head = _commit(
        repo,
        tmp_path,
        {
            "tests/fixtures/users.py": f'USERS = ["{REAL_EMAIL}", "qa@example.test"]\n',
            "app.py": 'ADMIN = "ops@example.com"\n',
        },
        "feat: fixtures",
    )
    return {"path": str(tmp_path), "repo": repo, "base": base, "head": head}


class TestPiiExcludeOption:
    def _review(self, fixture_repo, *extra, env=None):
        provider = ScriptedProvider(
            uses(call("read_file", {"path": "tests/fixtures/users.py"})), uses(submit())
        )
        with patch("semantic_diff.cli.build_provider", return_value=provider):
            result = CliRunner().invoke(
                main,
                ["review", "--base", "target", "--head", "feature"]
                + ["--repo", fixture_repo["path"], "--json", *extra],
                env=env,
            )
        assert result.exit_code == 0, result.output
        return repr(provider.requests), json.loads(result.stdout)

    def test_reserved_addresses_are_never_noise(self, fixture_repo):
        sent, report = self._review(fixture_repo)

        assert "qa@example.test" in sent and "ops@example.com" in sent
        assert REAL_EMAIL not in sent
        assert report["stats"]["redacted"] >= 1

    def test_flag_keeps_fixture_data_out_of_the_scan(self, fixture_repo):
        sent, report = self._review(fixture_repo, "--pii-exclude", "tests/**")

        assert REAL_EMAIL in sent
        assert report["stats"]["redacted"] == 0

    def test_env_takes_space_separated_patterns(self, fixture_repo):
        sent, _ = self._review(
            fixture_repo, env={"SEMANTIC_DIFF_PII_EXCLUDE": "docs/** **/fixtures/**"}
        )

        assert REAL_EMAIL in sent

    def test_mr_takes_the_flag_too(self, fixture_repo, mock_mr_analysis):
        with (
            patch("semantic_diff.cli.build_provider"),
            patch("semantic_diff.cli.LLMAnalyzer") as analyzer,
        ):
            analyzer.return_value.analyze.return_value = mock_mr_analysis
            result = CliRunner().invoke(
                main,
                ["mr", "--base", "target", "--head", "feature", "--repo", fixture_repo["path"]]
                + ["--json", "--pii-exclude", "**/fixtures/**"],
            )
        assert result.exit_code == 0, result.output
        _change_set, files, _context = analyzer.return_value.analyze.call_args.args

        assert REAL_EMAIL in "".join(f.diff_content for f in files)
