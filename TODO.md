# Semantic Diff — Open Source Roadmap

## Phase 1: Release Ready (MVP Hardening) ✅ DONE

### Testing
- [x] Unit tests for `git_parser.py` (38 tests)
- [x] Unit tests for `llm_analyzer.py` (31 tests)
- [x] Unit tests for formatters (19 tests)
- [x] Unit tests for CLI (18 tests)
- [x] Unit tests for models (8 tests)
- [x] **114 tests total, all passing**

### CI/CD
- [x] GitHub Actions workflow for tests
- [x] GitHub Actions workflow for linting (ruff, black)
- [ ] Dependabot for dependency updates
- [x] Release automation (tag → PyPI publish via twine)

### Documentation
- [x] README with badges, comparison table, examples
- [x] Add CONTRIBUTING.md
- [x] Add LICENSE (MIT)
- [ ] Add CHANGELOG.md
- [ ] Example outputs in /examples folder

### Code Quality
- [x] Type hints (Pydantic models)
- [ ] Docstrings for public methods
- [x] Error handling improvements
- [x] Retry logic for API calls
- [x] XSS protection in markdown output

---

## Phase 2: GitHub Action (Killer Feature) ✅ DONE

### Core Action
- [x] Create `action.yml` for GitHub Marketplace
- [x] Action inputs: `fail_on_risk`, `comment_on_pr`, `model`
- [x] PR comment with analysis summary
- [x] Status check (pass/fail based on risk level)
- [x] Support for `pull_request` events

### Integration
- [x] Example workflow in README
- [x] Self-analysis (dogfooding) in CI
- [ ] Marketplace listing
- [ ] Test on external repositories

---

## Phase 3: Multi-LLM Support

### OpenAI
- [ ] Add OpenAI adapter in analyzers/
- [ ] Environment variable: `SEMANTIC_DIFF_PROVIDER=openai|anthropic`
- [ ] Same prompt structure, different API calls
- [ ] Cost comparison in docs

### Local Models (Ollama)
- [ ] Ollama adapter for privacy-first users
- [ ] Test with Llama 3, Mistral, CodeLlama
- [ ] Document minimum model requirements
- [ ] Graceful degradation for smaller models

---

## Phase 4: Advanced Features

### Branch Diff
- [ ] `semantic-diff main..feature` syntax
- [ ] Aggregate analysis across multiple commits
- [ ] Summary of overall intent and risk
- [ ] Conflict detection hints

### Project Context
- [ ] `.semantic-diff.yaml` config file support
- [ ] Custom context injection ("this is a fintech app")
- [ ] Focus areas (security, performance, api-breaking)
- [ ] Ignore patterns (skip test files, docs)

### Changelog Generation
- [ ] `--changelog` flag for tag ranges
- [ ] Group commits by intent category
- [ ] Output formats: markdown, JSON, conventional-changelog
- [ ] Integration with release workflows

---

## Phase 5: Community & Growth

### Adoption
- [ ] Blog post: "Why We Built Semantic Diff"
- [ ] Reddit posts (r/programming, r/devops, r/git)
- [ ] Hacker News launch
- [ ] Dev.to / Hashnode articles

### Community
- [ ] Issue templates (bug, feature request)
- [ ] Discussion templates
- [ ] Good first issues labeled
- [ ] Response time SLA for issues

### Integrations (community-driven)
- [ ] VS Code extension (community)
- [ ] GitLab CI template
- [ ] Bitbucket Pipelines template
- [ ] Pre-commit hook

---

## Non-Goals (Keep It Simple)

- ❌ Web UI — CLI is enough
- ❌ Database/persistence — stateless by design
- ❌ Subscription/paid tier — free forever, it's marketing
- ❌ IDE plugins — let community build them
- ❌ Support for non-git VCS — git only

---

## Current Status

- [x] Core MVP working
- [x] Console formatter (Rich)
- [x] Markdown formatter + `--save` flag
- [x] JSON output
- [x] `semantic-diff init` — pre-push hook
- [x] `semantic-diff uninstall` — remove hook
- [x] **PyPI v0.2.0 published**
- [x] **GitHub repo public**
- [x] 114 tests passing
- [x] CI/CD with self-analysis

---

## Next Priority

1. **Launch post** (HN, Reddit) — get first users
2. **Multi-LLM support** — OpenAI, Ollama
3. **Branch diff** — `semantic-diff main..feature`

---

*Last updated: 2026-01-21*
