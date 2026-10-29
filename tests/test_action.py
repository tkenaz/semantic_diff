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
if [ "$1" = "review" ]; then
  echo '{"schema_version": 2, "risk_level": '"${STUB_RISK:-null}"', "verdict": "request_changes", "stats": {"submitted": '"${STUB_SUBMITTED:-true}"'}}'
else
  echo '{"schema_version": 2, "risk_assessment": {"overall_risk": "medium"}}'
fi
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
    "REVIEW": "false",
    "RULES_PATH": "",
    "PR_TITLE": 'feat: x"; rm -rf / #',
    "PR_BODY": "Why: because.\n$(touch pwned)",
}

REVIEW_ENV = {**PR_ENV, "REVIEW": "true"}


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


class TestReviewStep:
    def test_review_true_runs_the_agentic_reviewer_on_pull_requests(self, sandbox):
        result = _run_step(_steps()["analyze"], {**sandbox["env"], **REVIEW_ENV}, sandbox["cwd"])

        assert result.returncode == 0, result.stderr
        [call] = _calls(sandbox)
        assert call.startswith(f"review --base {'b' * 40} --head {'h' * 40} ")
        assert "--json" in call and "--save" in call
        assert "--rules" not in call

    def test_the_gate_value_is_the_cited_findings_risk(self, sandbox):
        env = {**sandbox["env"], **REVIEW_ENV, "STUB_RISK": '"high"'}

        _run_step(_steps()["analyze"], env, sandbox["cwd"])

        outputs = _outputs(sandbox)
        assert outputs["risk_level"] == "high"
        assert outputs["verdict"] == "request_changes"

    def test_a_review_without_cited_findings_reports_risk_none(self, sandbox):
        # risk_level null in the report: uncited observations never gate
        _run_step(_steps()["analyze"], {**sandbox["env"], **REVIEW_ENV}, sandbox["cwd"])

        assert _outputs(sandbox)["risk_level"] == "none"

    def test_an_unsubmitted_review_is_incomplete_not_none(self, sandbox):
        # Limits cut the review short: no findings because nothing was checked
        env = {**sandbox["env"], **REVIEW_ENV, "STUB_SUBMITTED": "false"}

        _run_step(_steps()["analyze"], env, sandbox["cwd"])

        assert _outputs(sandbox)["risk_level"] == "incomplete"

    def test_rules_path_reaches_the_cli(self, sandbox):
        env = {**sandbox["env"], **REVIEW_ENV, "RULES_PATH": "skills/compliance-review"}

        _run_step(_steps()["analyze"], env, sandbox["cwd"])

        [call] = _calls(sandbox)
        assert "--rules skills/compliance-review" in call

    def test_push_events_keep_the_one_shot_analysis(self, sandbox):
        env = {**sandbox["env"], **REVIEW_ENV, "EVENT_NAME": "push"}

        _run_step(_steps()["analyze"], env, sandbox["cwd"])

        assert _calls(sandbox)[0].startswith(f"analyze {'p' * 40} ")


class TestRiskGate:
    def _gate(self, sandbox, risk, threshold):
        env = {**sandbox["env"], "RISK": risk, "THRESHOLD": threshold}
        return _run_step(_steps()["Check risk threshold"], env, sandbox["cwd"])

    @pytest.mark.parametrize(
        "risk, threshold, fails",
        [
            ("low", "high", False),
            ("medium", "high", False),
            ("high", "high", True),
            ("critical", "high", True),
            ("critical", "low", True),
            ("low", "low", True),
        ],
    )
    def test_fails_when_risk_meets_or_exceeds_the_threshold(self, sandbox, risk, threshold, fails):
        result = self._gate(sandbox, risk, threshold)

        assert (result.returncode != 0) is fails, result.stdout + result.stderr

    def test_risk_none_never_fails_the_check(self, sandbox):
        # A review without cited findings gates nothing, whatever the threshold
        result = self._gate(sandbox, "none", "low")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "below threshold" in result.stdout

    def test_an_incomplete_review_fails_any_threshold(self, sandbox):
        result = self._gate(sandbox, "incomplete", "critical")

        assert result.returncode == 1
        assert "review is incomplete" in result.stdout

    def test_an_unknown_threshold_is_a_loud_error(self, sandbox):
        result = self._gate(sandbox, "low", "bogus")

        assert result.returncode == 1
        assert "Unknown fail_on_risk threshold" in result.stdout


HARNESS = """
const captured = {};
const github = { rest: { issues: {
  listComments: async () => ({ data: [] }),
  createComment: async (args) => { captured.body = args.body; },
  updateComment: async (args) => { captured.body = args.body; },
} } };
const context = { repo: { owner: "o", repo: "r" }, issue: { number: 1 } };
(async () => {
%s
})().then(() => process.stdout.write(captured.body));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="the comment script needs node")
class TestReviewComment:
    def _comment(self, sandbox, report):
        (sandbox["tmp"] / "semantic_diff_analysis.json").write_text(json.dumps(report))
        script = _steps()["Comment review on PR"]["with"]["script"]
        result = subprocess.run(
            ["node", "-e", HARNESS % script],
            env={**sandbox["env"]},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    REPORT = {
        "verdict": "request_changes",
        "risk_level": "high",
        "summary": "Fine.",
        "findings": [],
        "uncited": [],
        "diff_coverage": {"percent": 100},
        "stats": {"submitted": True},
        "review_model": "m",
    }

    def test_model_text_cannot_inject_html_mentions_or_lines(self, sandbox):
        finding = {
            "severity": "high",
            "file": "a.py",
            "line": 3,
            "title": "x\n**Gate risk:** none <img src=x>",
            "rule_id": "SEC-1`\n@maintainer",
            "source": "</details> @org/team",
        }
        body = self._comment(
            sandbox,
            {**self.REPORT, "summary": "<details> ping @maintainer", "findings": [finding]},
        )

        assert "<img" not in body and "<details> ping" not in body and "</details> @" not in body
        # Outside code spans (which GitHub never turns into mentions) every @ is broken
        assert "ping @maintainer" not in body and "@org" not in body
        [finding_line] = [line for line in body.splitlines() if line.startswith("- ")]
        assert "**Gate risk:** none" in finding_line  # inert text inside the finding line
        assert "`SEC-1' @maintainer`" in finding_line.replace("\u200b", "")

    def test_an_unsubmitted_review_shows_gate_risk_incomplete(self, sandbox):
        body = self._comment(
            sandbox, {**self.REPORT, "risk_level": None, "stats": {"submitted": False}}
        )

        assert "**Gate risk:** incomplete" in body
        assert "Incomplete review" in body
