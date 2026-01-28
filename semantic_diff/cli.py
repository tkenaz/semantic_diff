"""
CLI interface for semantic-diff
"""

import os
import stat
import sys
from pathlib import Path

import click

from semantic_diff.analyzers.llm_analyzer import LLMAnalyzer
from semantic_diff.formatters.console_formatter import ConsoleFormatter
from semantic_diff.formatters.markdown_formatter import MarkdownFormatter
from semantic_diff.parsers.git_parser import GitParser

REPORTS_DIR_NAME = "semantic_diff_reports"

PRE_PUSH_HOOK = """#!/bin/bash
# semantic-diff pre-push hook
# Analyzes commits before pushing to remote

remote="$1"
url="$2"

while read local_ref local_sha remote_ref remote_sha; do
    if [ "$local_sha" = "0000000000000000000000000000000000000000" ]; then
        continue
    fi

    echo "Running semantic-diff on: $local_sha"
    semantic-diff "$local_sha" --save

    if [ $? -ne 0 ]; then
        echo "semantic-diff analysis failed"
        exit 1
    fi
done

exit 0
"""


@click.group()
def main():
    """
    AI-powered semantic analysis of git commits.

    \b
    Commands:
      semantic-diff <commit>     Analyze a commit (default: HEAD)
      semantic-diff init         Install pre-push hook
      semantic-diff uninstall    Remove pre-push hook

    \b
    Examples:
      semantic-diff HEAD
      semantic-diff abc123 --save
      semantic-diff init
    """
    pass


@main.command(name="analyze")
@click.argument("commit_hash", default="HEAD")
@click.option("--repo", "-r", default=".", help="Path to git repository")
@click.option("--model", "-m", default=None, help="Model to use")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--save", "-s", is_flag=True, help="Save report to semantic_diff_reports/")
@click.option("--brief", "-b", is_flag=True, help="Brief output (intent + risk + top questions)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def analyze_cmd(
    commit_hash: str,
    repo: str,
    model: str,
    output_json: bool,
    save: bool,
    brief: bool,
    verbose: bool,
):
    """Analyze a git commit semantically."""
    _do_analyze(commit_hash, repo, model, output_json, save, brief, verbose)


# Also register as default command (when called without subcommand)
@main.result_callback()
@click.pass_context
def default_command(ctx, *args, **kwargs):
    """Handle direct invocation like: semantic-diff abc123"""
    pass


def _do_analyze(
    commit_hash: str,
    repo: str,
    model: str,
    output_json: bool,
    save: bool,
    brief: bool,
    verbose: bool,
):
    """Core analysis logic."""
    # Mutual exclusion: --brief and --verbose don't make sense together
    if brief and verbose:
        click.echo("Error: --brief and --verbose are mutually exclusive", err=True)
        sys.exit(1)

    try:
        if verbose:
            click.echo(f"Initializing parser for {repo}...")

        parser = GitParser(repo if repo != "." else None)

        if verbose:
            click.echo(f"Getting commit info for {commit_hash}...")

        commit_info = parser.get_commit_info(commit_hash)
        files = parser.get_file_changes(commit_hash)
        project_context = parser.get_project_context()

        if verbose:
            click.echo(f"Found {len(files)} changed files")
            click.echo(f"Project languages: {project_context.get('languages', [])}")

        if not files:
            click.echo("No changes found in this commit.", err=True)
            sys.exit(0)

        if verbose:
            click.echo("Calling LLM for analysis...")

        analyzer = LLMAnalyzer(model=model)
        analysis = analyzer.analyze(commit_info, files, project_context)

        if output_json:
            import json

            data = analysis.model_dump()
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            formatter = ConsoleFormatter(brief=brief)
            formatter.format(analysis)

        if save:
            git_root = Path(parser.repo.working_dir)
            reports_dir = git_root / REPORTS_DIR_NAME

            md_formatter = MarkdownFormatter()
            saved_path = md_formatter.save(analysis, reports_dir)
            click.echo(f"\nReport saved: {saved_path}")

    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--repo", "-r", default=".", help="Path to git repository")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing hook")
def init(repo: str, force: bool):
    """
    Install pre-push hook for automatic analysis.

    After installation, semantic-diff runs automatically before each push.
    Reports are saved to semantic_diff_reports/ in your project.
    """
    try:
        from git import InvalidGitRepositoryError, Repo

        try:
            git_repo = Repo(repo if repo != "." else os.getcwd())
        except InvalidGitRepositoryError:
            click.echo("Error: Not a git repository", err=True)
            sys.exit(1)

        hooks_dir = Path(git_repo.git_dir) / "hooks"
        hook_path = hooks_dir / "pre-push"

        if hook_path.exists() and not force:
            click.echo(f"Hook already exists: {hook_path}")
            click.echo("Use --force to overwrite")
            sys.exit(1)

        hook_path.write_text(PRE_PUSH_HOOK)
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)

        click.echo(f"Installed pre-push hook: {hook_path}")
        click.echo("")
        click.echo("semantic-diff will now run automatically before each push.")
        click.echo(f"Reports saved to: {git_repo.working_dir}/semantic_diff_reports/")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--repo", "-r", default=".", help="Path to git repository")
def uninstall(repo: str):
    """Remove the pre-push hook."""
    try:
        from git import InvalidGitRepositoryError, Repo

        try:
            git_repo = Repo(repo if repo != "." else os.getcwd())
        except InvalidGitRepositoryError:
            click.echo("Error: Not a git repository", err=True)
            sys.exit(1)

        hook_path = Path(git_repo.git_dir) / "hooks" / "pre-push"

        if not hook_path.exists():
            click.echo("No pre-push hook installed")
            sys.exit(0)

        content = hook_path.read_text()
        if "semantic-diff" not in content:
            click.echo("Existing hook is not from semantic-diff, not removing")
            sys.exit(1)

        hook_path.unlink()
        click.echo("Removed pre-push hook")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# Wrapper for backwards compatibility: semantic-diff HEAD
def cli():
    """Entry point that handles both commands and direct commit analysis."""
    args = sys.argv[1:]

    # If no args or first arg looks like a commit (not a known command)
    known_commands = ["init", "uninstall", "analyze", "--help", "-h"]

    if not args:
        # No args: analyze HEAD
        sys.argv = ["semantic-diff", "analyze", "HEAD"]
    elif args[0] not in known_commands and not args[0].startswith("-"):
        # First arg is not a command, treat as commit hash
        sys.argv = ["semantic-diff", "analyze"] + args
    elif args[0].startswith("-") and args[0] not in ["--help", "-h"]:
        # Flags without command: analyze HEAD with flags
        sys.argv = ["semantic-diff", "analyze", "HEAD"] + args

    main()


if __name__ == "__main__":
    cli()
