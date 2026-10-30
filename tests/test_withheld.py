"""
Tests for withheld files: the review tools never read the files where secrets
live by convention, whatever their contents, so redaction is a second layer
and not the only one; and the core install carries no vendor SDK.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from semantic_diff.cli import main
from semantic_diff.review.tools import Toolbox, ToolError
from semantic_diff.review.withheld import DEFAULT_WITHHELD, WithheldPaths
from tests.test_redaction import IN_CONFIG, IN_DIFF, secret_repo  # noqa: F401 (fixture)
from tests.test_review_agent import ScriptedProvider, call, submit, uses

tomllib = pytest.importorskip("tomllib")  # 3.11+

ROOT = Path(__file__).resolve().parent.parent


class TestWithheldPaths:
    @pytest.mark.parametrize(
        "path",
        [
            ".env",
            "deploy/.env.production",
            "certs/server.pem",
            "tls.key",
            "home/id_rsa",
            "home/id_ed25519.pub",
            ".npmrc",
            "infra/prod.tfvars",
            "secrets/db.yaml",
            "charts/app/secrets/token.txt",
            "aws/credentials",
        ],
    )
    def test_withheld_by_default(self, path):
        assert WithheldPaths()(path)

    @pytest.mark.parametrize(
        "path",
        [
            "src/environment.py",
            ".envoy.yaml",
            "secret_rules.py",
            "keys.py",
            "monkey.py",
            "docs/secrets.md",
            "src/credentials_test.py",
        ],
    )
    def test_ordinary_code_is_read(self, path):
        assert not WithheldPaths()(path)

    def test_a_pattern_with_a_slash_matches_the_whole_path(self):
        withheld = WithheldPaths(("config/*.yaml",))

        assert withheld("config/prod.yaml")
        assert not withheld("other/config/prod.yaml")


class TestToolbox:
    @pytest.fixture
    def toolbox(self, secret_repo):  # noqa: F811
        return Toolbox(
            secret_repo["repo"], head=secret_repo["head"].hexsha, base=secret_repo["base"].hexsha
        )

    @pytest.mark.parametrize("tool", ["read_file", "read_base"])
    def test_a_withheld_file_is_not_read(self, toolbox, tool):
        with pytest.raises(ToolError, match=r"\.env is withheld.*in the diff"):
            getattr(toolbox, tool)(".env")

    def test_grep_hides_hits_in_withheld_files_and_says_so(self, toolbox):
        out = toolbox.grep("TOKEN")

        assert out.startswith("config.py:1:")
        assert ".env" not in out.split("\n[")[0]
        assert out.endswith("[1 matches in withheld files not shown]")

    def test_the_citation_check_still_counts_lines(self, toolbox):
        # Internal, never sent to the model: a finding on .env can be cited
        assert toolbox.line_count("head", ".env") == 1


class TestReview:
    def test_more_files_can_be_withheld_from_the_command_line(self, secret_repo):  # noqa: F811
        provider = ScriptedProvider(
            uses(call("read_file", {"path": "config.py"}), call("read_file", {"path": ".env"})),
            uses(submit()),
        )
        with patch("semantic_diff.cli.build_provider", return_value=provider):
            result = CliRunner().invoke(
                main,
                ["review", "--base", "target", "--head", "feature", "--no-redact"]
                + ["--repo", secret_repo["path"], "--json", "--withhold", "config.py"],
            )

        assert result.exit_code == 0, result.output
        sent = repr(provider.requests)
        assert "config.py is withheld" in sent and ".env is withheld" in sent
        assert IN_CONFIG not in sent
        # Its diff is still the diff
        assert IN_DIFF in sent


class TestNoVendorSdkInTheCore:
    def test_anthropic_is_an_extra_not_a_dependency(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

        assert not any(d.startswith("anthropic") for d in project["dependencies"])
        assert any(d.startswith("anthropic") for d in project["optional-dependencies"]["anthropic"])

    def test_the_package_works_without_it(self):
        # A fresh interpreter in which `import anthropic` fails, as without the extra
        script = (
            "import sys; sys.modules['anthropic'] = None\n"
            "import semantic_diff.cli\n"
            "from semantic_diff.providers import *\n"
            "import os; os.environ['SEMANTIC_DIFF_PROVIDER'] = 'anthropic'\n"
            "from semantic_diff.providers import build_provider\n"
            "try:\n"
            "    build_provider(load_env=False)\n"
            "except ValueError as e:\n"
            "    print(e)\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=True
        )

        assert "pip install 'semantic-diff[anthropic]'" in out.stdout

    def test_the_action_asks_for_the_extra(self):
        action = (ROOT / "action.yml").read_text()

        assert '"${ACTION_PATH}[anthropic]"' in action
        assert '"semantic-diff[anthropic] @ git+https://' in action

    def test_the_defaults_are_documented_in_the_readme(self):
        readme = (ROOT / "README.md").read_text()

        assert all(pattern in readme for pattern in DEFAULT_WITHHELD)
