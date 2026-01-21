# Semantic Diff — Open Source Roadmap

## Phase 1: Release Ready (MVP Hardening)

### Testing
- [ ] Unit tests for `git_parser.py`
- [ ] Unit tests for `llm_analyzer.py`
- [ ] Unit tests for formatters (console, markdown)
- [ ] Integration tests (end-to-end with real commits)
- [ ] Test coverage target: 80%+

### CI/CD
- [ ] GitHub Actions workflow for tests
- [ ] GitHub Actions workflow for linting (ruff, black)
- [ ] Dependabot for dependency updates
- [ ] Release automation (tag → PyPI publish)

### Documentation
- [ ] Improve README with GIFs/screenshots
- [ ] Add CONTRIBUTING.md
- [ ] Add LICENSE (MIT)
- [ ] Add CHANGELOG.md
- [ ] Example outputs in /examples folder

### Code Quality
- [ ] Add type hints everywhere
- [ ] Docstrings for public methods
- [ ] Error handling improvements (graceful failures)
- [ ] Retry logic for API calls (already partially done)

---

## Phase 2: GitHub Action (Killer Feature)

### Core Action
- [ ] Create `action.yml` for GitHub Marketplace
- [ ] Action inputs: `fail-on-risk`, `comment-on-pr`, `model`
- [ ] PR comment with analysis summary
- [ ] Status check (pass/fail based on risk level)
- [ ] Support for `pull_request` and `push` events

### Integration
- [ ] Example workflow in README
- [ ] Test on real repositories
- [ ] Marketplace listing

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
- [x] Basic error handling
- [x] API retry logic

---

## Meta

**Every commit to this repo gets analyzed by semantic-diff itself.**

```bash
# After committing
semantic-diff HEAD --save
git add semantic_diff_reports/
git commit --amend --no-edit
```

---

*Last updated: 2026-01-18*
