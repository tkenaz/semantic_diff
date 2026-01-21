# Contributing to Semantic Diff

Thanks for your interest in contributing!

## Quick Start

```bash
# Clone
git clone https://github.com/kenaz-gmbh/semantic-diff.git
cd semantic-diff

# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run
semantic-diff HEAD
```

## Development

### Code Style

- **Formatter**: black
- **Linter**: ruff
- **Type hints**: required for public APIs

```bash
# Format
black semantic_diff

# Lint
ruff check semantic_diff

# Type check
mypy semantic_diff
```

### Tests

```bash
pytest
pytest --cov=semantic_diff  # with coverage
```

### Commit Messages

We follow conventional commits:

```
feat: add OpenAI support
fix: handle empty commits gracefully
docs: update README with examples
test: add parser unit tests
chore: update dependencies
```

## Pull Requests

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/amazing-feature`)
3. Make your changes
4. Run tests and linting
5. Commit with conventional message
6. Push and open PR

### PR Checklist

- [ ] Tests pass
- [ ] Linting passes
- [ ] New features have tests
- [ ] Documentation updated if needed

## Architecture

```
semantic_diff/
├── parsers/         # Git data extraction
├── analyzers/       # LLM analysis logic
├── formatters/      # Output formatting
├── models.py        # Pydantic data models
└── cli.py           # CLI interface
```

### Adding a New LLM Provider

1. Create `analyzers/your_provider.py`
2. Implement the same interface as `llm_analyzer.py`
3. Add provider selection logic in `cli.py`
4. Update `.env.example`

### Adding a New Formatter

1. Create `formatters/your_formatter.py`
2. Implement `format(analysis: SemanticAnalysis)` method
3. Add CLI flag in `cli.py`

## Questions?

Open an issue or discussion. We're friendly.

---

*Built with love by Kenaz GmbH*
