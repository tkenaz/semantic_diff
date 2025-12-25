"""
CLI interface for semantic-diff
"""
import click
from pathlib import Path
import sys
import os

from semantic_diff.parsers.git_parser import GitParser
from semantic_diff.analyzers.llm_analyzer import LLMAnalyzer
from semantic_diff.formatters.console_formatter import ConsoleFormatter


@click.command()
@click.argument('commit_hash', default='HEAD')
@click.option('--repo', '-r', default='.', help='Path to git repository')
@click.option('--model', '-m', default=None, help='Model to use (default: from .env)')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def main(commit_hash: str, repo: str, model: str, output_json: bool, verbose: bool):
    """
    Analyze a git commit semantically.
    
    COMMIT_HASH: The commit to analyze (default: HEAD)
    
    Examples:
    
        semantic-diff HEAD
        
        semantic-diff abc123
        
        semantic-diff HEAD~1 --repo /path/to/repo
    """
    try:
        # Initialize components
        if verbose:
            click.echo(f"Initializing parser for {repo}...")
        
        parser = GitParser(repo if repo != '.' else None)
        
        if verbose:
            click.echo(f"Getting commit info for {commit_hash}...")
        
        # Get commit data
        commit_info = parser.get_commit_info(commit_hash)
        files = parser.get_file_changes(commit_hash)
        project_context = parser.get_project_context()
        
        if verbose:
            click.echo(f"Found {len(files)} changed files")
            click.echo(f"Project languages: {project_context.get('languages', [])}")
        
        if not files:
            click.echo("No changes found in this commit.", err=True)
            sys.exit(0)
        
        # Analyze
        if verbose:
            click.echo("Calling LLM for analysis...")
        
        analyzer = LLMAnalyzer(model=model)
        analysis = analyzer.analyze(commit_info, files, project_context)
        
        # Output
        if output_json:
            import json
            # Convert to dict, handling enums
            data = analysis.model_dump()
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            formatter = ConsoleFormatter()
            formatter.format(analysis)
        
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
