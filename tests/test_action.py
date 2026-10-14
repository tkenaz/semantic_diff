"""
Tests for the GitHub Action (action.yml): its shell steps are executed for
real, with a stub `semantic-diff` on PATH that records how it was called.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ACTION = Path(__file__).parent.parent / "action.yml"
pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="action steps need jq")

STUB = """#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_LOG"
for arg in "$@"; do
  if [ "$arg" = "--description-file" ]; then DESC=1; continue; fi
  if [ -n "$DESC" ]; then cp "$arg" "$STUB_DIR/description_seen"; DESC=; fi
done
if [[ " $* " == *" --save "* ]]; then
  mkdir -p semantic_diff_reports && echo report > semantic_diff_reports/mr_x.md
  echo "Report saved: semantic_diff_reports/mr_x.md" >&2
fi
echo '{"schema_version": 2, "risk_assessment": {"overall_risk": "medium"}}'
"""


def _steps():
    return {
        s.get("id", s.get("name")): s for s in yaml.safe_load(ACTION.read_text())["runs"]["steps"]
    }


def _run_step(step, env, cwd):
    return subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def sandbox(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "semantic-diff"
    stub.write_text(STUB)
    stub.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    output = tmp_path / "github_output"
    output.touch()
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin",
        "STUB_LOG": str(tmp_path / "calls.log"),
        "STUB_DIR": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(tmp_path),
    }
    return {
        "env": env,
        "cwd": work,
        "log": tmp_path / "calls.log",
        "output": output,
        "tmp": tmp_path,
    }


def _calls(sandbox):
    return sandbox["log"].read_text().splitlines()


def _outputs(sandbox):
    text = sandbox["output"].read_text()
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1] for line in text.splitlines() if "=" in line
    }


PR_ENV = {
    "EVENT_NAME": "pull_request",
    "PR_BASE_SHA": "b" * 40,
    "PR_HEAD_SHA": "h" * 40,
    "PUSH_SHA": "p" * 40,
    "BASE_REF_INPUT": "",
    "PR_TITLE": 'feat: x"; rm -rf / #',
    "PR_BODY": "Why: because.\n$(touch pwned)",
}


class TestAnalyzeStep:
    def test_pull_request_analyzes_the_whole_range_in_one_call(self, sandbox):
        result = _run_step(_steps()["analyze"], {**sandbox["env"], **PR_ENV}, sandbox["cwd"])

        assert result.returncode == 0, result.stderr
        [call] = _calls(sandbox)
        assert call.startswith(f"mr --base {'b' * 40} --head {'h' * 40} ")
        assert "--json" in call and "--save" in call

    def test_pr_title_and_description_reach_the_cli_as_data(self, sandbox):
        _run_step(_steps()["analyze"], {**sandbox["env"], **PR_ENV}, sandbox["cwd"])

        [call] = _calls(sandbox)
        assert '--title feat: x"; rm -rf / #' in call
        assert (sandbox["tmp"] / "description_seen").read_text() == PR_ENV["PR_BODY"]
        assert not (sandbox["cwd"] / "pwned").exists()

    def test_base_ref_input_overrides_the_pr_base(self, sandbox):
        env = {**sandbox["env"], **PR_ENV, "BASE_REF_INPUT": "origin/release"}

        _run_step(_steps()["analyze"], env, sandbox["cwd"])

        assert _calls(sandbox)[0].startswith("mr --base origin/release ")

    def test_push_analyzes_the_pushed_commit(self, sandbox):
        env = {**sandbox["env"], **PR_ENV, "EVENT_NAME": "push"}

        result = _run_step(_steps()["analyze"], env, sandbox["cwd"])

        assert result.returncode == 0, result.stderr
        [call] = _calls(sandbox)
        assert call.startswith(f"analyze {'p' * 40} ")

    def test_outputs_risk_json_and_report_path(self, sandbox):
        _run_step(_steps()["analyze"], {**sandbox["env"], **PR_ENV}, sandbox["cwd"])

        outputs = _outputs(sandbox)
        assert outputs["risk_level"] == "medium"
        assert outputs["report_path"] == "semantic_diff_reports/mr_x.md"
        saved = Path(sandbox["tmp"]) / "semantic_diff_analysis.json"
        assert json.loads(saved.read_text())["schema_version"] == 2

    def test_run_scripts_take_event_data_only_through_env(self):
        for step in _steps().values():
            assert "${{" not in step.get("run", ""), step.get("name")
