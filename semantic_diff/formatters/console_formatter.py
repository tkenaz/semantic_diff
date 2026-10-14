"""
Console formatter for semantic diff output using Rich
"""

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from semantic_diff.models import RiskLevel, SemanticAnalysis


class ConsoleFormatter:
    """Formats SemanticAnalysis for terminal output"""

    RISK_COLORS = {
        RiskLevel.LOW: "green",
        RiskLevel.MEDIUM: "yellow",
        RiskLevel.HIGH: "red",
        RiskLevel.CRITICAL: "bold red",
    }

    RISK_ICONS = {
        RiskLevel.LOW: "✓",
        RiskLevel.MEDIUM: "⚠",
        RiskLevel.HIGH: "⚡",
        RiskLevel.CRITICAL: "🔥",
    }

    def __init__(self, brief: bool = False):
        self.console = Console()
        self.brief = brief

    def _risk_style(self, level: RiskLevel) -> str:
        return self.RISK_COLORS.get(level, "white")

    def _risk_icon(self, level: RiskLevel) -> str:
        return self.RISK_ICONS.get(level, "•")

    def format(self, analysis: SemanticAnalysis) -> None:
        """Print formatted analysis to console"""

        if self.brief:
            self._format_brief(analysis)
        else:
            self._format_full(analysis)

    def _format_brief(self, analysis: SemanticAnalysis) -> None:
        """Print compact analysis output"""

        # Header - compact
        self.console.print()
        risk = analysis.risk_assessment
        risk_icon = self._risk_icon(risk.overall_risk)
        risk_color = self._risk_style(risk.overall_risk)

        self.console.print(
            Panel(
                f"[bold]{escape(analysis.change_set.title)}[/bold]\n"
                f"[dim]{self._scope_line(analysis)}[/dim]",
                title="📋 Semantic Diff",
                border_style="blue",
            )
        )

        # Intent - summary only
        confidence_bar = "█" * int(analysis.intent.confidence * 10) + "░" * (
            10 - int(analysis.intent.confidence * 10)
        )
        self.console.print(
            Panel(
                f"{analysis.intent.summary}\n\n"
                f"[dim]Confidence: [{confidence_bar}] {analysis.intent.confidence:.0%}[/dim]",
                title="🎯 Intent",
                border_style="green",
            )
        )

        # Risk - overall only
        risk_text = Text()
        risk_text.append(
            f"Overall Risk: {risk_icon} {risk.overall_risk.value.upper()}",
            style=f"bold {risk_color}",
        )
        if risk.breaking_changes:
            risk_text.append("  ⚠️  BREAKING CHANGES", style="bold red")

        self.console.print(Panel(risk_text, title="⚠️  Risk", border_style=risk_color))

        # Top questions - show all CRITICAL/HIGH, then fill up to 3 with others
        if analysis.review_questions:
            # Always show CRITICAL and HIGH priority questions
            critical_high = [
                q
                for q in analysis.review_questions
                if q.priority in (RiskLevel.CRITICAL, RiskLevel.HIGH)
            ]
            others = [
                q
                for q in analysis.review_questions
                if q.priority not in (RiskLevel.CRITICAL, RiskLevel.HIGH)
            ]

            # Show all critical/high, then fill remaining slots up to 3 minimum
            questions_to_show = critical_high.copy()
            remaining_slots = max(0, 3 - len(critical_high))
            questions_to_show.extend(others[:remaining_slots])

            questions_text = Text()
            for q in questions_to_show:
                icon = self._risk_icon(q.priority)
                color = self._risk_style(q.priority)
                questions_text.append(f"{icon} ", style=color)
                questions_text.append(f"{q.question}\n")

            # Show count if there are more hidden
            hidden_count = len(analysis.review_questions) - len(questions_to_show)
            if hidden_count > 0:
                questions_text.append(
                    f"... and {hidden_count} more (use full mode to see all)", style="dim"
                )

            self.console.print(Panel(questions_text, title="❓ Top Questions", border_style="cyan"))

        self.console.print()

    @staticmethod
    def _commit_count(analysis: SemanticAnalysis) -> str:
        return f"{len(analysis.change_set.commits)} commits"

    def _scope_line(self, analysis: SemanticAnalysis) -> str:
        parts = [analysis.change_set.ref, f"{len(analysis.files_changed)} files"]
        if analysis.change_set.kind == "merge_request":
            parts.append(self._commit_count(analysis))
        if analysis.diff_coverage is not None:
            parts.append(f"diff {analysis.diff_coverage.percent}%")
        return " • ".join(parts)

    def _when_or_size(self, analysis: SemanticAnalysis) -> str:
        if analysis.change_set.kind == "merge_request":
            return self._commit_count(analysis)
        return analysis.change_set.date or ""

    @staticmethod
    def _coverage_suffix(analysis: SemanticAnalysis) -> str:
        if analysis.diff_coverage is None:
            return ""
        return f" • diff {analysis.diff_coverage.percent}%"

    def _warn_unseen(self, analysis: SemanticAnalysis) -> None:
        cov = analysis.diff_coverage
        if cov is None or not cov.omitted:
            return
        noun = "file" if len(cov.omitted) == 1 else "files"
        self.console.print(
            f"[yellow]⚠ {len(cov.omitted)} {noun} not shown to the model "
            f"(over the diff budget): {escape(', '.join(cov.omitted))}[/yellow]"
        )

    def _format_full(self, analysis: SemanticAnalysis) -> None:
        """Print full analysis output"""

        # Header
        self.console.print()
        self.console.print(
            Panel(
                f"[bold]{escape(analysis.change_set.title)}[/bold]\n\n"
                f"[dim]{analysis.change_set.ref} by "
                f"{escape(', '.join(analysis.change_set.authors))}[/dim]\n"
                f"[dim]{self._when_or_size(analysis)}"
                f"{self._coverage_suffix(analysis)}[/dim]",
                title="📋 Semantic Diff Analysis",
                border_style="blue",
            )
        )
        self._warn_unseen(analysis)

        # Files changed summary
        files_table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        files_table.add_column("File", style="cyan")
        files_table.add_column("Change", style="dim")
        files_table.add_column("+", style="green", justify="right")
        files_table.add_column("-", style="red", justify="right")
        files_table.add_column("Lang", style="dim")

        for f in analysis.files_changed[:10]:  # Limit to 10
            files_table.add_row(
                f.path[:50] + "..." if len(f.path) > 50 else f.path,
                f.change_type,
                str(f.additions),
                str(f.deletions),
                f.language or "-",
            )

        if len(analysis.files_changed) > 10:
            files_table.add_row(f"... and {len(analysis.files_changed) - 10} more", "", "", "", "")

        self.console.print(Panel(files_table, title="📁 Files Changed", border_style="dim"))

        # Intent
        confidence_bar = "█" * int(analysis.intent.confidence * 10) + "░" * (
            10 - int(analysis.intent.confidence * 10)
        )
        self.console.print(
            Panel(
                f"[bold]{analysis.intent.summary}[/bold]\n\n"
                f"{analysis.intent.reasoning}\n\n"
                f"[dim]Confidence: [{confidence_bar}] {analysis.intent.confidence:.0%}[/dim]",
                title="🎯 Intent",
                border_style="green",
            )
        )

        # Impact Map
        impact_text = Text()

        if analysis.impact_map.direct_impacts:
            impact_text.append("Direct Impacts:\n", style="bold")
            for impact in analysis.impact_map.direct_impacts:
                icon = self._risk_icon(impact.severity)
                color = self._risk_style(impact.severity)
                impact_text.append(f"  {icon} ", style=color)
                impact_text.append(f"{impact.area}: ", style="bold")
                impact_text.append(f"{impact.description}\n")
            impact_text.append("\n")

        if analysis.impact_map.indirect_impacts:
            impact_text.append("Indirect Impacts:\n", style="bold")
            for impact in analysis.impact_map.indirect_impacts:
                icon = self._risk_icon(impact.severity)
                color = self._risk_style(impact.severity)
                impact_text.append(f"  {icon} ", style=color)
                impact_text.append(f"{impact.area}: ", style="bold")
                impact_text.append(f"{impact.description}\n")
            impact_text.append("\n")

        if analysis.impact_map.affected_components:
            impact_text.append("Affected Components: ", style="bold")
            impact_text.append(", ".join(analysis.impact_map.affected_components))

        self.console.print(Panel(impact_text, title="🗺️  Impact Map", border_style="yellow"))

        # Risk Assessment
        risk = analysis.risk_assessment
        risk_color = self._risk_style(risk.overall_risk)
        risk_icon = self._risk_icon(risk.overall_risk)

        risk_text = Text()
        risk_text.append(
            f"Overall Risk: {risk_icon} {risk.overall_risk.value.upper()}\n\n",
            style=f"bold {risk_color}",
        )

        if risk.breaking_changes:
            risk_text.append("⚠️  BREAKING CHANGES DETECTED\n", style="bold red")
        if risk.requires_migration:
            risk_text.append("📦 Migration required\n", style="bold yellow")

        if risk.risks:
            risk_text.append("\nIdentified Risks:\n", style="bold")
            for r in risk.risks:
                icon = self._risk_icon(r.severity)
                color = self._risk_style(r.severity)
                risk_text.append(f"\n  {icon} ", style=color)
                risk_text.append(f"[{r.severity.value}] ", style=f"bold {color}")
                risk_text.append(f"{r.description}\n")
                if r.mitigation:
                    risk_text.append(f"     💡 Mitigation: {r.mitigation}\n", style="dim")
                if r.edge_cases:
                    risk_text.append(
                        f"     ⚡ Edge cases: {', '.join(r.edge_cases)}\n", style="dim"
                    )

        self.console.print(Panel(risk_text, title="⚠️  Risk Assessment", border_style=risk_color))

        # Review Questions
        if analysis.review_questions:
            questions_text = Text()
            for i, q in enumerate(analysis.review_questions, 1):
                icon = self._risk_icon(q.priority)
                color = self._risk_style(q.priority)
                questions_text.append(f"{i}. ", style="bold")
                questions_text.append(f"{q.question}\n", style="bold")
                questions_text.append(f"   {icon} ", style=color)
                questions_text.append(f"{q.context}\n\n", style="dim")

            self.console.print(
                Panel(questions_text, title="❓ Review Questions", border_style="cyan")
            )

        # Footer
        self.console.print()
        self.console.print(
            f"[dim]Analysis by {analysis.analysis_model} | "
            f"{analysis.tokens_used:,} tokens | "
            f"{analysis.analysis_timestamp}[/dim]"
        )
        self.console.print()
