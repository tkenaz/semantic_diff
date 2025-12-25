# semantic-diff

AI-powered semantic analysis of git commits. Goes beyond `git diff` to show **intent**, **impact**, **risk**, and **review questions**.

## What it does

Regular `git diff` shows *what* changed. `semantic-diff` shows:

- **🎯 Intent** — What was the developer trying to accomplish? (not what changed, but *why*)
- **🗺️ Impact Map** — What parts of the system are affected directly and indirectly?
- **⚠️ Risk Assessment** — What could break? Edge cases? Breaking changes?
- **❓ Review Questions** — What should a reviewer ask the author?

## Installation

```bash
# Clone the repo
git clone git@github.com:tkenaz/semantic_diff.git
cd semantic_diff

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install
pip install -e .
```

## Configuration

Create a `.env` file:

```bash
ANTHROPIC_API_KEY=sk-ant-...
SEMANTIC_DIFF_MODEL=claude-sonnet-4-5-20250929  # or claude-opus-4-5-20251101
SEMANTIC_DIFF_MAX_RETRIES=3  # optional, API retry attempts
SEMANTIC_DIFF_MAX_WAIT=30.0  # optional, max total retry wait time in seconds
```

## Usage

```bash
# Analyze HEAD commit in current repo
semantic-diff

# Analyze specific commit
semantic-diff abc123

# Analyze commit in another repo
semantic-diff HEAD --repo /path/to/repo

# Output as JSON (for piping to other tools)
semantic-diff HEAD --json

# Verbose mode
semantic-diff HEAD -v
```

## Example Output

```
╭──────────────────── 📋 Semantic Diff Analysis ────────────────────╮
│ Fix authentication bypass in login endpoint                       │
│                                                                    │
│ abc12345 by developer@example.com                                  │
│ 2024-12-22T10:30:00                                                │
╰────────────────────────────────────────────────────────────────────╯

╭──────────────────────── 🎯 Intent ────────────────────────╮
│ Prevent unauthorized access by validating session tokens  │
│ before processing login requests.                         │
│                                                            │
│ Confidence: [████████░░] 85%                               │
╰────────────────────────────────────────────────────────────╯

╭──────────────────── ⚠️ Risk Assessment ───────────────────╮
│ Overall Risk: ⚡ HIGH                                      │
│                                                            │
│ ⚠️  BREAKING CHANGES DETECTED                              │
│                                                            │
│ Identified Risks:                                          │
│   ⚡ [high] Existing sessions may be invalidated           │
│      💡 Mitigation: Add migration for active sessions      │
╰────────────────────────────────────────────────────────────╯
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black semantic_diff
ruff check semantic_diff
```

## License

MIT — Kenaz GmbH
