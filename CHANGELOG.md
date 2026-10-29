# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (breaking)
- `semantic-diff review --json` schema is now `schema_version` 2 (KEN-315):
  findings are split into two channels. `findings` holds only **cited**
  findings — backed by a rule card from a configured corpus (`rule_id`
  verified in code against the corpus, brackets and stray spaces ignored;
  `source` is printed from the card itself, not from the model; a card
  without a `source:` line gives none, so it never gates) and by evidence
  that checked out (the cited line exists, the file was seen, the quoted
  `evidence` is in the diff within a few lines of the cited line, with or
  without the line-number prefix the model was shown, and holds at least six
  letters or digits — `}` proves nothing). Everything else lands in `uncited` with
  honest severity: observations without a card, invented rule ids, findings
  whose evidence failed a check. New top-level `risk_level` carries the worst
  severity among cited findings (null without any) — the only value a CI gate
  should read; `uncited` never flips a pass to a fail.
- The review Markdown report gained a `Gate risk` line (`incomplete` when the
  model never submitted), a `Rule:` line and the
  quoted evidence on cited findings, and an `Uncited observations` section.

### Added
- Tool calling (`converse`) on the Anthropic adapter, with prompt caching and
  merged tool results — `semantic-diff review` now runs against the default
  Anthropic provider (`ANTHROPIC_API_KEY`), not only OpenAI-compatible
  gateways. This is what lets the GitHub Action run the reviewer.
- `semantic-diff review --rules DIR` (env `SEMANTIC_DIFF_RULES`): a rule
  corpus (`INDEX.md` + `rules/*.md`, cards headed `### [ID] ...`). INDEX.md is
  shown to the model up front, rule files load on demand through a `read_rules`
  tool, and submitted rule ids are verified against the corpus.
- GitHub Action: `review: true` runs the agentic reviewer on pull requests
  (new inputs `review` and `rules_path`, new output `verdict`); the PR comment
  shows the verdict, cited findings and uncited observations, and
  `fail_on_risk` reads cited findings only. The risk-threshold step now treats
  `none` as never failing and rejects unknown thresholds loudly (and no longer
  needs bash 4). A review the model never submitted (a turn, token or context
  limit cut it short) reports `risk_level` output `incomplete` and fails any
  `fail_on_risk` threshold: nothing checked means nothing passed. Model text in
  the PR comment is escaped (no HTML, no @-mentions, one-line fields stay on
  one line).

### Fixed
- `.env` is now found in the current directory (the analyzed repository), not
  searched upward from the installed package, so it works for `pip install`
  users and not only for editable checkouts; it is also loaded before options
  are parsed, so `.env`-only settings such as `SEMANTIC_DIFF_RULES` and
  `SEMANTIC_DIFF_MAX_DIFF_TOKENS` take effect. In CI (`CI` set) `.env` is never
  read: the working tree is the change under review, and a `.env` committed
  in a pull request could otherwise point `ANTHROPIC_BASE_URL` at another host
  and receive the API key.
- GitHub Action used as a local action (`uses: ./`) installed the CLI from
  `main` instead of the checkout it runs from; it now installs its own code.
- Test fixtures and docs referenced a previous-generation model id; defaults
  and examples now consistently use `claude-sonnet-5-5` (with
  `claude-opus-5-5` called out for deeper reviews).

## [0.3.0] - 2026-10-14

### Changed (breaking)
- JSON output: `commit_hash`, `commit_message`, `author`, `date` moved into a
  nested `change_set` object, which describes either a commit or a merge request:

  | 0.2.x | 0.3.0 |
  |-------|-------|
  | `.commit_hash` | `.change_set.head_sha` |
  | `.commit_message` | `.change_set.title` + `.change_set.description` |
  | `.author` | `.change_set.authors[]` |
  | `.date` | `.change_set.date` (null for merge requests) |

  New top-level `schema_version` (= 2): check it before reading fields.
- Diagnostics (`--verbose`, "Report saved", errors) go to stderr, so `--json`
  stdout stays parseable when piped (e.g. into `jq`)

### Added
- `semantic-diff mr --base <ref> [--head <ref>]`: analyze a whole merge
  request from the merge base (same diff as GitLab's Changes tab)
- `--gitlab-env`: take base, head, title and description from GitLab MR
  pipeline variables
- Pluggable providers: Anthropic (default) and OpenAI-compatible gateways
  (`SEMANTIC_DIFF_PROVIDER=openai`, extra `semantic-diff[openai]`)
- One retry policy for all providers; honours `Retry-After`
- Diff budget (`--max-diff-tokens`, default 60000): riskiest files first,
  trimmed at hunk boundaries; reports state diff coverage and name every
  file the model did not see
- `diff_coverage` and `schema_version` in JSON output
- GitHub Action: pull requests are analyzed as a whole (merge base..head)
  with the PR title and description as intent; one LLM call per run
  instead of two; the PR comment flags partial diff coverage
- `semantic-diff review`: agentic merge request review. The model reads around
  the change with read-only tools (`read_file`, `read_base`, `grep`,
  `list_dir`, `git_log`) over git objects at head/base, and submits findings
  tied to lines. Bounded by turns, cumulative input tokens and per-turn
  context; a limit forces a final submission and is named in the report.
- Every review finding is checked in code: the cited line exists (head or
  base) and the file was actually seen by the model.
- Review report as Markdown and JSON (`schema_version` 1), with turns, tool
  calls, tokens (cache reads/writes) and files read.
- Providers: tool-calling conversations (`converse`) with prompt caching on
  the OpenAI-compatible adapter; retries cover them too.

### Security
- `gitpython>=3.1.58`: earlier versions are affected by CVE-2026-42215,
  CVE-2026-44243 and later advisories (the suite passes on 3.1.0 through 3.2.0)

### Fixed
- Long answers no longer fail as broken JSON: the output limit is 32,000
  tokens (was 4096) and configurable (`--max-output-tokens` /
  `SEMANTIC_DIFF_MAX_OUTPUT_TOKENS`); an answer cut off at the limit is
  reported as such instead of `Unterminated string`
- MR description cannot close its own untrusted fence in the prompt
- `+`/`-` line counts for lines like `++i;` / `--x`
- Initial commits: every added line is marked `+`
- Retry loop crashed with `max_retries=0`; SDK retries no longer stack with ours
- `from semantic_diff.providers import *` works without the `openai` extra
- Brief mode printed raw `[dim]` markup
- The test suite no longer makes real API calls
- GitHub Action: event data reaches shell steps only through env
  (no `${{ }}` inside scripts); the comment links the right repository

## [0.2.2] - 2026-10-12

### Fixed
- Take the first text block of the response, not `content[0]`

## [0.2.1] - 2026-10-12

### Added
- `--brief` flag for compact output

### Fixed
- GitHub Action installs the CLI from the action's own ref; default model sonnet-5-5
- Findings from self-analysis

## [0.2.0] - 2026-01-21

### Added
- `semantic-diff init` command to install pre-push hook for automatic analysis
- `semantic-diff uninstall` command to remove the hook
- XSS protection in markdown formatter (escape user-controlled content)
- CI skips semantic-analysis on forks (no secrets access) and dependabot PRs

### Fixed
- CLI now properly routes commands (`init`, `uninstall`, `analyze`)
- Black formatting updated to 26.1.0
- All 114 tests passing

## [0.1.0] - 2025-12-27

### Added
- Initial release
- Core semantic analysis using Claude API
- Console output with Rich formatting
- Markdown report generation (`--save` flag)
- JSON output (`--json` flag)
- GitHub Action for PR analysis
- Retry logic for API calls
- Pydantic models for structured analysis

[Unreleased]: https://github.com/tkenaz/semantic_diff/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/tkenaz/semantic_diff/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/tkenaz/semantic_diff/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/tkenaz/semantic_diff/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/tkenaz/semantic_diff/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/tkenaz/semantic_diff/releases/tag/v0.1.0
