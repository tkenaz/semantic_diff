# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/tkenaz/semantic_diff/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/tkenaz/semantic_diff/releases/tag/v0.1.0
