"""
LLM-based semantic analyzer using Claude
"""
import os
import json
from datetime import datetime
from typing import List, Optional
import anthropic
from dotenv import load_dotenv

from semantic_diff.models import (
    FileChange, SemanticAnalysis, Intent, ImpactMap, Impact,
    RiskAssessment, Risk, ReviewQuestion, RiskLevel
)


class LLMAnalyzer:
    """Analyzes code changes using Claude for semantic understanding"""
    
    ANALYSIS_PROMPT = """You are a senior code reviewer analyzing a git commit. Your task is to provide semantic analysis that goes beyond what a simple diff shows.

## Commit Information
- **Hash:** {commit_hash}
- **Message:** {commit_message}
- **Author:** {author}
- **Date:** {date}

## Project Context
{project_context}

## Files Changed
{files_summary}

## Detailed Diffs
{diffs}

---

Analyze this commit and provide a structured response in the following JSON format:

```json
{{
    "intent": {{
        "summary": "One sentence describing WHAT the developer was trying to accomplish (not what changed, but WHY)",
        "reasoning": "2-3 sentences explaining your reasoning",
        "confidence": 0.0-1.0
    }},
    "impact_map": {{
        "direct_impacts": [
            {{"area": "affected area", "description": "how it's affected", "severity": "low|medium|high|critical"}}
        ],
        "indirect_impacts": [
            {{"area": "indirectly affected area", "description": "potential ripple effects", "severity": "low|medium|high|critical"}}
        ],
        "affected_components": ["list", "of", "components"]
    }},
    "risk_assessment": {{
        "overall_risk": "low|medium|high|critical",
        "risks": [
            {{
                "description": "specific risk",
                "severity": "low|medium|high|critical",
                "mitigation": "how to mitigate",
                "edge_cases": ["edge case 1", "edge case 2"]
            }}
        ],
        "breaking_changes": true/false,
        "requires_migration": true/false
    }},
    "review_questions": [
        {{
            "question": "Question for the author",
            "context": "Why this question matters",
            "priority": "low|medium|high|critical"
        }}
    ]
}}
```

Focus on:
1. **Intent**: What problem is being solved? What's the motivation?
2. **Impact**: What else in the system might be affected? Consider imports, API consumers, tests.
3. **Risk**: What could break? What edge cases exist? Is this backwards compatible?
4. **Questions**: What would you ask the author in a code review?

Be specific and actionable. Avoid generic observations."""

    def __init__(self, model: Optional[str] = None):
        load_dotenv()
        
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        
        self.model = model or os.getenv('SEMANTIC_DIFF_MODEL', 'claude-sonnet-4-5-20250929')
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.last_usage = None
    
    def _format_files_summary(self, files: List[FileChange]) -> str:
        """Format file changes for the prompt"""
        lines = []
        for f in files:
            lang = f"[{f.language}]" if f.language else ""
            lines.append(f"- {f.path} ({f.change_type}) +{f.additions}/-{f.deletions} {lang}")
        return "\n".join(lines)
    
    def _format_diffs(self, files: List[FileChange], max_total_chars: int = 15000) -> str:
        """Format diffs for the prompt, respecting token limits"""
        diffs = []
        total_chars = 0
        
        for f in files:
            if total_chars >= max_total_chars:
                diffs.append(f"\n... (truncated - {len(files) - len(diffs)} more files)")
                break
            
            header = f"\n### {f.path} ({f.change_type})\n```{f.language or 'diff'}\n"
            content = f.diff_content
            footer = "\n```\n"
            
            # Truncate individual file if too long
            available = max_total_chars - total_chars - len(header) - len(footer)
            if len(content) > available:
                content = content[:available] + "\n... (truncated)"
            
            diff_block = header + content + footer
            diffs.append(diff_block)
            total_chars += len(diff_block)
        
        return "\n".join(diffs)
    
    def _format_project_context(self, context: dict) -> str:
        """Format project context for the prompt"""
        lines = [
            f"- **Languages:** {', '.join(context.get('languages', ['unknown']))}",
            f"- **Package Manager:** {context.get('package_manager', 'unknown')}",
            f"- **Has Tests:** {'Yes' if context.get('has_tests') else 'No'}",
            f"- **Has CI:** {'Yes' if context.get('has_ci') else 'No'}",
            f"- **Root Files:** {', '.join(context.get('root_files', [])[:10])}",
            f"- **Directories:** {', '.join(context.get('directories', [])[:10])}",
        ]
        return "\n".join(lines)
    
    def _parse_response(self, response_text: str) -> dict:
        """Extract JSON from Claude's response"""
        # Try to find JSON block
        if "```json" in response_text:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            json_str = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            json_str = response_text[start:end].strip()
        else:
            # Try to parse the whole response as JSON
            json_str = response_text.strip()
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\nResponse: {response_text[:500]}")
    
    def analyze(
        self,
        commit_info: dict,
        files: List[FileChange],
        project_context: dict
    ) -> SemanticAnalysis:
        """
        Analyze a commit using Claude.
        Returns structured SemanticAnalysis.
        """
        # Build the prompt
        prompt = self.ANALYSIS_PROMPT.format(
            commit_hash=commit_info['short_hash'],
            commit_message=commit_info['message'],
            author=commit_info['author'],
            date=commit_info['date'],
            project_context=self._format_project_context(project_context),
            files_summary=self._format_files_summary(files),
            diffs=self._format_diffs(files)
        )
        
        # Call Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        self.last_usage = {
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens,
            'total_tokens': response.usage.input_tokens + response.usage.output_tokens
        }
        
        # Parse response
        response_text = response.content[0].text
        data = self._parse_response(response_text)
        
        # Build structured response
        intent = Intent(
            summary=data['intent']['summary'],
            reasoning=data['intent']['reasoning'],
            confidence=data['intent']['confidence']
        )
        
        impact_map = ImpactMap(
            direct_impacts=[
                Impact(
                    area=i['area'],
                    description=i['description'],
                    severity=RiskLevel(i['severity'])
                ) for i in data['impact_map'].get('direct_impacts', [])
            ],
            indirect_impacts=[
                Impact(
                    area=i['area'],
                    description=i['description'],
                    severity=RiskLevel(i['severity'])
                ) for i in data['impact_map'].get('indirect_impacts', [])
            ],
            affected_components=data['impact_map'].get('affected_components', [])
        )
        
        risk_assessment = RiskAssessment(
            overall_risk=RiskLevel(data['risk_assessment']['overall_risk']),
            risks=[
                Risk(
                    description=r['description'],
                    severity=RiskLevel(r['severity']),
                    mitigation=r.get('mitigation'),
                    edge_cases=r.get('edge_cases', [])
                ) for r in data['risk_assessment'].get('risks', [])
            ],
            breaking_changes=data['risk_assessment'].get('breaking_changes', False),
            requires_migration=data['risk_assessment'].get('requires_migration', False)
        )
        
        review_questions = [
            ReviewQuestion(
                question=q['question'],
                context=q['context'],
                priority=RiskLevel(q.get('priority', 'medium'))
            ) for q in data.get('review_questions', [])
        ]
        
        return SemanticAnalysis(
            commit_hash=commit_info['hash'],
            commit_message=commit_info['message'],
            author=commit_info['author'],
            date=commit_info['date'],
            files_changed=files,
            intent=intent,
            impact_map=impact_map,
            risk_assessment=risk_assessment,
            review_questions=review_questions,
            analysis_model=self.model,
            analysis_timestamp=datetime.now().isoformat(),
            tokens_used=self.last_usage['total_tokens']
        )
