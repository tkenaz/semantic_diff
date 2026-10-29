import os

import dotenv
import pytest

from semantic_diff import user_env
from semantic_diff.user_env import load_user_env


@pytest.fixture
def loaded(monkeypatch):
    calls = []
    monkeypatch.setattr(user_env, "find_dotenv", lambda **k: "repo/.env")
    monkeypatch.setattr(user_env, "load_dotenv", calls.append)
    return calls


@pytest.mark.parametrize("ci", ["true", "1", "yes"])
def test_ci_never_reads_the_env_file_of_the_change_under_review(monkeypatch, loaded, ci):
    monkeypatch.setenv("CI", ci)

    load_user_env()

    assert loaded == []


@pytest.mark.parametrize("ci", [None, "", "false", "0"])
def test_outside_ci_the_env_file_of_the_working_directory_loads(monkeypatch, loaded, ci):
    if ci is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci)

    load_user_env()

    assert loaded == ["repo/.env"]


def test_a_committed_env_file_cannot_redirect_the_key_in_ci(tmp_path, monkeypatch):
    # The real dotenv, the attack as it would land in a pull request
    monkeypatch.setattr(user_env, "load_dotenv", dotenv.load_dotenv)
    (tmp_path / ".env").write_text("ANTHROPIC_BASE_URL=https://attacker.example\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("CI", "true")

    load_user_env()

    assert "ANTHROPIC_BASE_URL" not in os.environ
