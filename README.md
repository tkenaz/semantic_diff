# semantic-diff

[![PyPI version](https://badge.fury.io/py/semantic-diff.svg)](https://pypi.org/project/semantic-diff/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AI-powered semantic analysis of git commits and merge requests. Goes beyond `git diff` to show **intent**, **impact**, **risk**, and **review questions** - or runs an agentic review that reads the code around the change.

## What it does

Regular `git diff` shows *what* changed. `semantic-diff` shows:

| | git diff | semantic-diff |
|---|---|---|
| **What** | Lines added/removed | Same |
| **Why** | - | Intent behind the change |
| **Risk** | - | What could break, edge cases |
| **Impact** | - | Direct and indirect effects |
| **Review** | - | Questions to ask the author |

## Installation

```bash
pip install semantic-diff
```

## Quick Start

```bash
# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Analyze a commit
semantic-diff HEAD

# Enable automatic analysis before every push
semantic-diff init
```

That's it! Now every `git push` will automatically analyze your commits and save reports.

## How It Works

### Manual Analysis

```bash
# Analyze HEAD commit
semantic-diff

# Analyze specific commit
semantic-diff abc123

# Save report to file
semantic-diff HEAD --save

# Output as JSON
semantic-diff HEAD --json
```

### Automatic Analysis (Pre-Push Hook)

```bash
# Install the hook (once per project)
semantic-diff init

# Now every push triggers analysis automatically
git push  # → runs semantic-diff, saves report, then pushes
```

### Reports

Reports are saved to `semantic_diff_reports/` in your project root:

```
my-project/
├── semantic_diff_reports/
│   ├── abc12345_20240115_143022.md         # commit
│   ├── mr_def67890_20240115_152341.md      # semantic-diff mr
│   ├── review_def67890_20240115_160512.md  # semantic-diff review
│   └── ...
├── src/
└── ...
```

Each report includes:
- Commit metadata
- Intent analysis with confidence score
- Impact map (direct and indirect effects)
- Risk assessment with mitigations
- Review questions prioritized by importance
- Diff coverage: which files the model did not see, if any

### JSON output

`--json` prints the analysis to stdout; diagnostics go to stderr, so it pipes
cleanly into `jq`. The output carries a top-level `schema_version` - check it
before reading fields.

**0.3.0 changed the schema (version 2).** Commit fields moved into a nested
`change_set`, which describes either a commit or a merge request:

| 0.2.x | 0.3.0 |
|-------|-------|
| `.commit_hash` | `.change_set.head_sha` |
| `.commit_message` | `.change_set.title` + `.change_set.description` |
| `.author` | `.change_set.authors[]` |
| `.date` | `.change_set.date` (null for merge requests) |

`semantic-diff review --json` has its own schema (`schema_version` 1). See
[CHANGELOG.md](CHANGELOG.md) for details.

### GitHub Action

Add to your workflow to analyze PRs automatically. A pull request is analyzed
as a whole (merge base..head, the same diff as the PR's Files tab), with its
title and description as the stated intent - one LLM call per run. On `push`,
the pushed commit is analyzed.

```yaml
# .github/workflows/semantic-diff.yml
name: Semantic Diff

on: [pull_request]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: tkenaz/semantic_diff@v0.3.0
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          comment_on_pr: true
          fail_on_risk: high  # optional: block merge on high risk
```

| Input | Default | |
|-------|---------|---|
| `anthropic_api_key` | - | Required |
| `model` | `claude-sonnet-5-5` | Any Anthropic model id |
| `comment_on_pr` | `true` | Post (or update) one PR comment |
| `fail_on_risk` | `never` | `low`, `medium`, `high`, `critical` or `never` |
| `base_ref` | PR base | Override the base to compare against |

Outputs: `risk_level`, `analysis_json`, `report_path`.

The action runs `semantic-diff mr` against Anthropic. It does not run the
agentic `review` and does not take an OpenAI-compatible gateway; for those,
call the CLI from your own workflow step.

## Example Output

### Analysis Overview

![Example Output](assets/example-output.png)

*Intent analysis with 98% confidence, risk assessment, and review questions*

### What It Finds

![Risk Assessment](assets/risk-assessment.png)

*Real example: semantic-diff analyzing itself found XSS vulnerabilities, CI issues, and security misconfigurations*

## Configuration

Create a `.env` file in your project or set environment variables:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional
SEMANTIC_DIFF_MODEL=claude-sonnet-5-5  # or claude-opus-5-5
```

### OpenAI-compatible gateways

Any gateway that speaks the OpenAI Chat Completions protocol (LiteLLM, vLLM,
corporate LLM hubs, OpenAI itself) works through the `openai` provider:

```bash
pip install 'semantic-diff[openai]'

SEMANTIC_DIFF_PROVIDER=openai
SEMANTIC_DIFF_BASE_URL=https://your-gateway.example/v1
SEMANTIC_DIFF_API_KEY=...
SEMANTIC_DIFF_MODEL=claude-sonnet-4.6   # required: model ids differ per gateway
```

Retries (rate limits honour `Retry-After`, timeouts, 5xx) are handled once for
all providers: `SEMANTIC_DIFF_MAX_RETRIES` (attempts, default 3) and
`SEMANTIC_DIFF_MAX_WAIT` (seconds, default 30).

### Diff budget

Large changes are not cut blindly. Diffs are packed into a token budget
(`--max-diff-tokens` / `SEMANTIC_DIFF_MAX_DIFF_TOKENS`, default 60,000):
code first, then migrations, CI/infra, tests, docs. A file that does not fit
whole is trimmed at hunk boundaries, never mid-line. Lock files, generated
output and binaries are listed but never shown. The model is told which files
it did not see, and every report states the coverage, e.g.
`Diff coverage: 87% of changed lines` plus the trimmed/not-shown files.

### Agentic review

`semantic-diff review` goes further than `mr`: instead of one call over the
diff, an agent reads around the change - whole functions, callers, the file
before the change, history - with read-only tools, and submits findings tied
to lines.

```bash
semantic-diff review --base origin/dev --save
semantic-diff review --gitlab-env --json   # inside a GitLab MR pipeline
```

- Tools read git objects at the merge request's head and base, never the
  working tree: uncommitted files are invisible to the model.
- Every review is bounded: `--max-turns` (`SEMANTIC_DIFF_MAX_TURNS`, default
  25), `--max-input-tokens` (`SEMANTIC_DIFF_MAX_INPUT_TOKENS`, default
  1,000,000, cached tokens included) and the diff shown up front
  (`--max-diff-tokens` / `SEMANTIC_DIFF_REVIEW_DIFF_TOKENS`, default 30,000).
  When a limit is reached the model gets one last turn to submit what it has,
  and the report says which limit cut the review short.
- Each finding is checked in code: does the cited line exist (after the
  change, or only before it), and did the model actually see the file. The
  report flags findings that fail either check.
- Needs a provider with tool calling: `SEMANTIC_DIFF_PROVIDER=openai`
  (any OpenAI-compatible gateway). Prompt caching is used where the gateway
  supports it, so each turn re-reads the conversation from cache.

## Commands

| Command | Description |
|---------|-------------|
| `semantic-diff` | Analyze HEAD commit |
| `semantic-diff <hash>` | Analyze specific commit (long form: `semantic-diff analyze <hash>`) |
| `semantic-diff mr --base origin/main` | Analyze a whole merge request (merge-base..HEAD) |
| `semantic-diff mr --gitlab-env` | Same, inside a GitLab MR pipeline (reads `CI_MERGE_REQUEST_*`) |
| `semantic-diff review --base origin/main` | Agentic review of a merge request (see above; `openai` provider only) |
| `semantic-diff init` | Install pre-push hook |
| `semantic-diff uninstall` | Remove pre-push hook |

Options for `analyze`, `mr` and `review`:

| Option | Description |
|--------|-------------|
| `--save`, `-s` | Save report to `semantic_diff_reports/` |
| `--json` | Output as JSON (see [JSON output](#json-output)) |
| `--model`, `-m` | Model id (overrides `SEMANTIC_DIFF_MODEL`) |
| `--repo`, `-r` | Path to the git repository (default: current directory) |
| `--verbose`, `-v` | Progress and errors in detail, on stderr |
| `--brief`, `-b` | Intent, risk and top questions only (`analyze`, `mr`) |
| `--max-diff-tokens N` | Diff budget for the prompt (default 60000; 30000 for `review`) |
| `--max-output-tokens N` | Room for the model's answer (default 32000; env `SEMANTIC_DIFF_MAX_OUTPUT_TOKENS`; `analyze`, `mr`) |

Picking the range for `mr` and `review`:

| Option | Description |
|--------|-------------|
| `--base REF` | Target branch the MR merges into (required unless `--gitlab-env`) |
| `--head REF` | Source ref (default: `HEAD`) |
| `--title TEXT` | MR title - the strongest intent signal |
| `--description-file PATH` | File with the MR description |
| `--gitlab-env` | Read base, head, title and description from GitLab MR pipeline variables |

`review` adds `--max-turns` and `--max-input-tokens` (see
[Agentic review](#agentic-review)).

## Development

```bash
git clone https://github.com/tkenaz/semantic_diff.git
cd semantic_diff
pip install -e ".[dev]"
pytest
```

## Support

- **Bug reports & features**: [GitHub Issues](https://github.com/tkenaz/semantic_diff/issues)
- **Custom integrations or enterprise**: [hello@kenaz.ai](mailto:hello@kenaz.ai)

## License

MIT — [Kenaz GmbH](https://kenaz.ai)

---

*Built with 🖤 by [Kenaz GmbH](https://kenaz.ai) — AI tools for developers*
