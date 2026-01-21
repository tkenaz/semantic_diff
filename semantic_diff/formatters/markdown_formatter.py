"""
Markdown formatter for semantic diff output - saves to files
"""
from pathlib import Path
from datetime import datetime

from semantic_diff.models import SemanticAnalysis, RiskLevel


class MarkdownFormatter:
    """Formats SemanticAnalysis as Markdown for file storage"""

    RISK_ICONS = {
        RiskLevel.LOW: "✓",
        RiskLevel.MEDIUM: "⚠️",
        RiskLevel.HIGH: "⚡",
        RiskLevel.CRITICAL: "🔥",
    }

    def _risk_icon(self, level: RiskLevel) -> str:
        return self.RISK_ICONS.get(level, "•")

    def format(self, analysis: SemanticAnalysis) -> str:
        """Generate markdown string from analysis"""
        lines = []

        # Header
        lines.append(f"# Semantic Diff: {analysis.commit_hash[:8]}")
        lines.append("")
        lines.append(f"**Commit:** `{analysis.commit_hash}`")
        lines.append(f"**Author:** {analysis.author}")
        lines.append(f"**Date:** {analysis.date}")
        lines.append("")
        lines.append(f"> {analysis.commit_message}")
        lines.append("")

        # Files Changed
        lines.append("## 📁 Files Changed")
        lines.append("")
        lines.append("| File | Change | + | - | Lang |")
        lines.append("|------|--------|---|---|------|")
        for f in analysis.files_changed:
            path = f.path[:50] + "..." if len(f.path) > 50 else f.path
            lines.append(f"| `{path}` | {f.change_type} | {f.additions} | {f.deletions} | {f.language or '-'} |")
        lines.append("")

        # Intent
        lines.append("## 🎯 Intent")
        lines.append("")
        lines.append(f"**{analysis.intent.summary}**")
        lines.append("")
        lines.append(analysis.intent.reasoning)
        lines.append("")
        confidence_pct = int(analysis.intent.confidence * 100)
        lines.append(f"*Confidence: {confidence_pct}%*")
        lines.append("")

        # Impact Map
        lines.append("## 🗺️ Impact Map")
        lines.append("")

        if analysis.impact_map.direct_impacts:
            lines.append("### Direct Impacts")
            for impact in analysis.impact_map.direct_impacts:
                icon = self._risk_icon(impact.severity)
                lines.append(f"- {icon} **{impact.area}**: {impact.description}")
            lines.append("")

        if analysis.impact_map.indirect_impacts:
            lines.append("### Indirect Impacts")
            for impact in analysis.impact_map.indirect_impacts:
                icon = self._risk_icon(impact.severity)
                lines.append(f"- {icon} **{impact.area}**: {impact.description}")
            lines.append("")

        if analysis.impact_map.affected_components:
            lines.append(f"**Affected Components:** {', '.join(analysis.impact_map.affected_components)}")
            lines.append("")

        # Risk Assessment
        lines.append("## ⚠️ Risk Assessment")
        lines.append("")
        risk = analysis.risk_assessment
        icon = self._risk_icon(risk.overall_risk)
        lines.append(f"**Overall Risk:** {icon} {risk.overall_risk.value.upper()}")
        lines.append("")

        if risk.breaking_changes:
            lines.append("🚨 **BREAKING CHANGES DETECTED**")
            lines.append("")
        if risk.requires_migration:
            lines.append("📦 **Migration required**")
            lines.append("")

        if risk.risks:
            lines.append("### Identified Risks")
            lines.append("")
            for r in risk.risks:
                icon = self._risk_icon(r.severity)
                lines.append(f"#### {icon} [{r.severity.value}] {r.description}")
                if r.mitigation:
                    lines.append(f"- 💡 **Mitigation:** {r.mitigation}")
                if r.edge_cases:
                    lines.append(f"- ⚡ **Edge cases:** {', '.join(r.edge_cases)}")
                lines.append("")

        # Review Questions
        if analysis.review_questions:
            lines.append("## ❓ Review Questions")
            lines.append("")
            for i, q in enumerate(analysis.review_questions, 1):
                icon = self._risk_icon(q.priority)
                lines.append(f"### {i}. {q.question}")
                lines.append(f"{icon} {q.context}")
                lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"*Analysis by {analysis.analysis_model} | {analysis.tokens_used:,} tokens | {analysis.analysis_timestamp}*")

        return "\n".join(lines)

    def save(self, analysis: SemanticAnalysis, output_dir: Path) -> Path:
        """Save analysis to markdown file in output_dir"""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Filename: <short_hash>_<timestamp>.md
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{analysis.commit_hash[:8]}_{timestamp}.md"
        filepath = output_dir / filename

        content = self.format(analysis)
        filepath.write_text(content, encoding="utf-8")

        return filepath
