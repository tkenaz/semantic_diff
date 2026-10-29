"""
CLI interface for semantic-diff
"""

import json
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import click
from rich.console import Console
from rich.markdown import Markdown

from semantic_diff.analyzers.llm_analyzer import DEFAULT_OUTPUT_TOKENS, LLMAnalyzer
from semantic_diff.change_set import from_commit, from_range
from semantic_diff.diff_pack import DEFAULT_BUDGET_TOKENS
from semantic_diff.formatters.console_formatter import ConsoleFormatter
from semantic_diff.formatters.markdown_formatter import MarkdownFormatter
from semantic_diff.gitlab_env import gitlab_mr_context
from semantic_diff.models import ChangeSet, FileChange
from semantic_diff.parsers.git_parser import GitParser
from semantic_diff.providers import build_provider
from semantic_diff.review.agent import ReviewAgent, ReviewLimits
from semantic_diff.review.corpus import RulesCorpus
from semantic_diff.review.markdown import ReviewMarkdownFormatter
from semantic_diff.review.tools import Toolbox
from semantic_diff.review.transcript import file_sink
from semantic_diff.user_env import load_user_env

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
    AI-powered semantic analysis of git commits and merge requests.

    \b
    Commands:
      semantic-diff <commit>     Analyze a commit (default: HEAD)
      semantic-diff mr           Analyze a merge request (base..head)
      semantic-diff review       Review a merge request with an agent that reads the code
      semantic-diff init         Install pre-push hook
      semantic-diff uninstall    Remove pre-push hook

    \b
    Examples:
      semantic-diff HEAD
      semantic-diff abc123 --save
      semantic-diff mr --base origin/dev
      semantic-diff mr --gitlab-env --json
      semantic-diff review --base origin/dev --save
      semantic-diff init
    """
    pass


def _output_options(command):
    """Options shared by every analysis command."""
    options = [
        click.option("--repo", "-r", default=".", help="Path to git repository"),
        click.option("--model", "-m", default=None, help="Model to use"),
        click.option("--json", "output_json", is_flag=True, help="Output as JSON"),
        click.option("--save", "-s", is_flag=True, help="Save report to semantic_diff_reports/"),
        click.option(
            "--brief", "-b", is_flag=True, help="Brief output (intent + risk + top questions)"
        ),
        click.option("--verbose", "-v", is_flag=True, help="Verbose output"),
        click.option(
            "--max-diff-tokens",
            type=click.IntRange(min=1),
            default=DEFAULT_BUDGET_TOKENS,
            show_default=True,
            envvar="SEMANTIC_DIFF_MAX_DIFF_TOKENS",
            help="Token budget for diffs in the prompt; the report states coverage",
        ),
        click.option(
            "--max-output-tokens",
            type=click.IntRange(min=1),
            default=DEFAULT_OUTPUT_TOKENS,
            show_default=True,
            envvar="SEMANTIC_DIFF_MAX_OUTPUT_TOKENS",
            help="Ceiling for the model's answer; only tokens actually written are billed",
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


@main.command(name="analyze")
@click.argument("commit_hash", default="HEAD")
@_output_options
def analyze_cmd(commit_hash: str, **output):
    """Analyze a git commit semantically."""

    def collect(parser: GitParser):
        change_set = from_commit(parser.get_commit_info(commit_hash))
        return change_set, parser.get_file_changes(commit_hash)

    _run(collect, **output)


def _range_options(command):
    """Options that pick a merge request range, shared by mr and review."""
    options = [
        click.option(
            "--base", default=None, help="Target ref the MR merges into (e.g. origin/dev)"
        ),
        click.option("--head", default=None, help="Source ref (default: HEAD)"),
        click.option("--title", default=None, help="MR title - the strongest intent signal"),
        click.option(
            "--description-file",
            type=click.File("r"),
            default=None,
            help="File with the MR description",
        ),
        click.option(
            "--gitlab-env",
            is_flag=True,
            help="Read base/head/title/description from GitLab MR pipeline variables",
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


def _range_collector(
    base: Optional[str],
    head: Optional[str],
    title: Optional[str],
    description_file,
    gitlab_env: bool,
) -> Callable[[GitParser], Tuple[Optional[ChangeSet], List[FileChange]]]:
    def collect(parser: GitParser):
        context = gitlab_mr_context(os.environ) if gitlab_env else {}
        base_ref = base or context.get("base")
        if not base_ref:
            raise ValueError("--base is required (or run with --gitlab-env in an MR pipeline)")
        head_ref = head or context.get("head") or "HEAD"

        try:
            info = parser.get_range_info(base_ref, head_ref)
        except ValueError as e:
            if "Could not find commit" in str(e):
                raise ValueError(
                    f"{e}. Shallow clone? Set GIT_DEPTH: 0 for this job, "
                    f"or fetch the commit: git fetch origin {base_ref}"
                ) from e
            raise
        if not info["commits"]:
            return None, []

        description = (
            description_file.read() if description_file else context.get("description", "")
        )
        change_set = from_range(info, title=title or context.get("title"), description=description)
        return change_set, parser.get_range_changes(base_ref, head_ref)

    return collect


@main.command(name="mr")
@_range_options
@_output_options
def mr_cmd(
    base: Optional[str],
    head: Optional[str],
    title: Optional[str],
    description_file,
    gitlab_env: bool,
    **output,
):
    """Analyze a whole merge request: merge-base(base, head)..head."""
    _run(_range_collector(base, head, title, description_file, gitlab_env), **output)


@main.command(name="review")
@_range_options
@click.option("--repo", "-r", default=".", help="Path to git repository")
@click.option("--model", "-m", default=None, help="Model to use (needs tool calling)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--save", "-s", is_flag=True, help="Save report to semantic_diff_reports/")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option(
    "--max-turns",
    type=click.IntRange(min=1),
    default=ReviewLimits.max_turns,
    show_default=True,
    envvar="SEMANTIC_DIFF_MAX_TURNS",
    help="Model turns before the review must be submitted",
)
@click.option(
    "--max-input-tokens",
    type=click.IntRange(min=1),
    default=ReviewLimits.max_input_tokens,
    show_default=True,
    envvar="SEMANTIC_DIFF_MAX_INPUT_TOKENS",
    help="Input tokens summed over all turns (cached ones included) before wrap-up",
)
@click.option(
    "--max-diff-tokens",
    type=click.IntRange(min=1),
    default=ReviewLimits.diff_budget_tokens,
    show_default=True,
    envvar="SEMANTIC_DIFF_REVIEW_DIFF_TOKENS",
    help="Diff shown up front; the agent reads the rest on demand",
)
@click.option(
    "--rules",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    envvar="SEMANTIC_DIFF_RULES",
    help="Rule corpus directory (INDEX.md + rules/*.md); enables cited findings",
)
@click.option(
    "--transcript",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the whole review conversation here as JSON lines",
)
def review_cmd(
    base: Optional[str],
    head: Optional[str],
    title: Optional[str],
    description_file,
    gitlab_env: bool,
    repo: str,
    model: Optional[str],
    output_json: bool,
    save: bool,
    verbose: bool,
    max_turns: int,
    max_input_tokens: int,
    max_diff_tokens: int,
    rules: Optional[Path],
    transcript: Optional[Path],
):
    """Review a merge request: an agent reads around the change and reports findings."""
    with _reported_errors(verbose):
        parser = GitParser(repo if repo != "." else None)
        collect = _range_collector(base, head, title, description_file, gitlab_env)
        change_set, files = collect(parser)
        if change_set is None or not files:
            click.echo("No changes found.", err=True)
            sys.exit(0)

        provider = build_provider(model=model)
        if not _supports_tools(provider):
            raise ValueError(
                "The configured provider does not support tool calling, which review needs."
            )
        corpus = RulesCorpus(rules) if rules else None
        if verbose:
            click.echo(f"Reviewing {len(files)} changed files with {provider.model}...", err=True)
            if corpus:
                click.echo(
                    f"Rule corpus: {rules} ({len(corpus.rule_ids)} cards in "
                    f"{len(corpus.rule_files)} files)",
                    err=True,
                )

        limits = ReviewLimits(
            max_turns=max_turns,
            max_input_tokens=max_input_tokens,
            diff_budget_tokens=max_diff_tokens,
        )
        toolbox = Toolbox(parser.repo, head=change_set.head_sha, base=change_set.base_sha)
        sink = file_sink(transcript) if transcript else None
        report = ReviewAgent(provider, toolbox, limits, corpus=corpus, transcript=sink).review(
            change_set, files
        )

        formatter = ReviewMarkdownFormatter()
        if output_json:
            click.echo(report.model_dump_json(indent=2))
        else:
            Console().print(Markdown(formatter.format(report)))

        if save:
            saved_path = formatter.save(report, Path(parser.repo.working_dir) / REPORTS_DIR_NAME)
            click.echo(f"\nReport saved: {saved_path}", err=True)


def _supports_tools(provider) -> bool:
    # RetryingProvider forwards converse() to the adapter it wraps
    return callable(getattr(getattr(provider, "inner", provider), "converse", None))


# Also register as default command (when called without subcommand)
@main.result_callback()
@click.pass_context
def default_command(ctx, *args, **kwargs):
    """Handle direct invocation like: semantic-diff abc123"""
    pass


def _run(
    collect: Callable[[GitParser], Tuple[Optional[ChangeSet], List[FileChange]]],
    repo: str,
    model: Optional[str],
    output_json: bool,
    save: bool,
    brief: bool,
    verbose: bool,
    max_diff_tokens: int,
    max_output_tokens: int,
):
    """Shared pipeline: collect the change set, analyze it, render/save the result."""
    # Mutual exclusion: --brief and --verbose don't make sense together
    if brief and verbose:
        click.echo("Error: --brief and --verbose are mutually exclusive", err=True)
        sys.exit(1)

    with _reported_errors(verbose):
        if verbose:
            click.echo(f"Initializing parser for {repo}...", err=True)

        parser = GitParser(repo if repo != "." else None)
        change_set, files = collect(parser)
        project_context = parser.get_project_context()

        if verbose:
            click.echo(f"Found {len(files)} changed files", err=True)
            click.echo(f"Project languages: {project_context.get('languages', [])}", err=True)

        if change_set is None or not files:
            click.echo("No changes found.", err=True)
            sys.exit(0)

        if verbose:
            click.echo("Calling LLM for analysis...", err=True)

        analyzer = LLMAnalyzer(
            build_provider(model=model),
            max_diff_tokens=max_diff_tokens,
            max_output_tokens=max_output_tokens,
        )
        analysis = analyzer.analyze(change_set, files, project_context)

        if output_json:
            click.echo(json.dumps(analysis.model_dump(), indent=2, default=str))
        else:
            ConsoleFormatter(brief=brief).format(analysis)

        if save:
            reports_dir = Path(parser.repo.working_dir) / REPORTS_DIR_NAME
            saved_path = MarkdownFormatter().save(analysis, reports_dir)
            click.echo(f"\nReport saved: {saved_path}", err=True)


@contextmanager
def _reported_errors(verbose: bool):
    """Any failure becomes "Error: ..." on stderr and exit code 1 (sys.exit passes through)."""
    try:
        yield
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
HELP_FLAGS = ("--help", "-h")


def route_args(args: List[str]) -> List[str]:
    """
    Map console-script arguments to a command: bare commits and bare flags mean
    `analyze`. Known commands come from the click group itself, so a newly
    registered command is routed correctly without touching this function.
    """
    if not args:
        return ["analyze", "HEAD"]
    first = args[0]
    if first in main.commands or first in HELP_FLAGS:
        return args
    if first.startswith("-"):
        return ["analyze", "HEAD"] + args
    return ["analyze"] + args


def cli():
    """Entry point that handles both commands and direct commit analysis."""
    # Before click parses: options with envvar= (SEMANTIC_DIFF_RULES, ...) read
    # os.environ then, so a .env loaded later by build_provider would be too late.
    load_user_env()
    sys.argv = ["semantic-diff"] + route_args(sys.argv[1:])
    main()


if __name__ == "__main__":
    cli()
