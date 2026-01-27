# Perspectives & Feedback

Collected insights from HN, Reddit, and other sources. Use for prioritizing improvements.

---

## HN Feedback (2026-01-27)

### Naming: "Commit Review" vs "Semantic Diff"
> "That's commit review not semantic diff"

**Valid point.** The name is evolutionary — started as semantic analysis of diffs, grew into full commit review tool. Consider:
- Keep name (brand recognition, PyPI, GitHub)
- Add subtitle: "semantic-diff: AI-powered commit review"
- Clarify in README first paragraph

### "Why" Should Be in Commit Message
> "why some changes happened should be in the commit body rather than try to figure it out after the fact"

**Philosophical difference.** Tool can't read author's mind. But:
- Surfacing questions has value even without answers
- Forces reviewer to ASK the author
- Good commits + semantic-diff = even better review

### Redundancy in Output
> "the CLAUDE_NOTES.md massive content reduction appears in Impact Map, Risk Assessment, Review Questions"

**This is real pain.** Same issue mentioned 3x = noise. 

**TODO:**
- [ ] Add `--verbosity` flag (minimal/normal/verbose)
- [ ] Add `--sections` flag to pick what to show
- [ ] Deduplicate cross-section mentions
- [ ] Consider "collapsed" view for repeated items

### Report Length
> "Personally will've preferred overall report be shorter"

**User preference varies.** Some want detail, some want summary.

**TODO:**
- [ ] Add `--brief` mode (just risk level + top 3 questions)
- [ ] Add `.semantic-diff.yaml` config for defaults
- [ ] Consider "executive summary" section at top

### Dependabot Skip
> "Why skip dependabot PRs specifically? Shouldn't dependabot updates also be semantically analyzed?"

**Good question.** Current logic: dependabot = noise. But:
- Security vulnerabilities in deps ARE important
- Breaking API changes in deps ARE important

**TODO:**
- [ ] Reconsider dependabot skip
- [ ] Or add `--include-dependabot` flag
- [ ] Different analysis mode for deps (focus on breaking changes)

### Indirect Impacts — Heuristics vs LLM
> "modules impacted by a change... probably doable heuristically rather requiring an LLM"

**Partially true.** Static analysis can find:
- Function call graphs
- Import dependencies
- Type changes

But LLM catches:
- Semantic meaning changes
- "This validation change affects all downstream consumers"
- Non-obvious connections

**Consider:** Hybrid approach — heuristic for obvious, LLM for subtle.

---

## My Own Observations

### What Works Well
- Pre-push hook — catches issues before they hit PR
- Risk ranking — critical/high/medium actually useful
- Review questions — even unanswered, they prompt thinking

### What Needs Work
- Output too verbose by default
- No config file support yet
- Single model only (Claude) — need OpenAI/Ollama options
- No way to give project context ("this is a payments app, security matters")

### Low-Hanging Fruit
1. `--brief` flag for short output
2. `--sections` flag to filter output
3. `.semantic-diff.yaml` for project defaults
4. Better deduplication in output

### Bigger Lifts
1. Multi-LLM support (Phase 3 in TODO)
2. Branch diff `main..feature` (Phase 4)
3. Project context injection (Phase 4)

---

## Response Template for HN

```
Fair points, thanks for actually trying it.

The naming is evolutionary — started as semantic analysis of diffs, grew into commit review. Name stuck.

You're right about redundancy. Same issue in 3 sections is noise. Adding --verbosity and --sections flags to control output.

The "why was this deleted" questions — tool can't answer, but surfacing the question for reviewer has value. At least you know to ask the author.

Good callout on dependabot, reconsidering that skip logic.

Re: indirect impacts + heuristics — fair. Static analysis can catch call graphs. LLM catches semantic meaning changes that heuristics miss. Hybrid approach worth exploring.

Appreciate the detailed feedback.
```

---

*Last updated: 2026-01-27*
