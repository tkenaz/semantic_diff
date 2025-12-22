"""
Console formatter for semantic diff output using Rich
"""
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.text import Text
from rich import box

from semantic_diff.models import SemanticAnalysis, RiskLevel


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
    
    def __init__(self):
        self.console = Console()
    
    def _risk_style(self, level: RiskLevel) -> str:
        return self.RISK_COLORS.get(level, "white")
    
    def _risk_icon(self, level: RiskLevel) -> str:
        return self.RISK_ICONS.get(level, "•")
    
    def format(self, analysis: SemanticAnalysis) -> None:
        """Print formatted analysis to console"""
        
        # Header
        self.console.print()
        self.console.print(Panel(
            f"[bold]{analysis.commit_message}[/bold]\n\n"
            f"[dim]{analysis.commit_hash[:8]} by {analysis.author}[/dim]\n"
            f"[dim]{analysis.date}[/dim]",
            title="📋 Semantic Diff Analysis",
            border_style="blue"
        ))
        
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
                f.language or "-"
            )
        
        if len(analysis.files_changed) > 10:
            files_table.add_row(
                f"... and {len(analysis.files_changed) - 10} more",
                "", "", "", ""
            )
        
        self.console.print(Panel(files_table, title="📁 Files Changed", border_style="dim"))
        
        # Intent
        confidence_bar = "█" * int(analysis.intent.confidence * 10) + "░" * (10 - int(analysis.intent.confidence * 10))
        self.console.print(Panel(
            f"[bold]{analysis.intent.summary}[/bold]\n\n"
            f"{analysis.intent.reasoning}\n\n"
            f"[dim]Confidence: [{confidence_bar}] {analysis.intent.confidence:.0%}[/dim]",
            title="🎯 Intent",
            border_style="green"
        ))
        
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
        risk_text.append(f"Overall Risk: {risk_icon} {risk.overall_risk.value.upper()}\n\n", style=f"bold {risk_color}")
        
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
                    risk_text.append(f"     ⚡ Edge cases: {', '.join(r.edge_cases)}\n", style="dim")
        
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
            
            self.console.print(Panel(questions_text, title="❓ Review Questions", border_style="cyan"))
        
        # Footer
        self.console.print()
        self.console.print(
            f"[dim]Analysis by {analysis.analysis_model} | "
            f"{analysis.tokens_used:,} tokens | "
            f"{analysis.analysis_timestamp}[/dim]"
        )
        self.console.print()
