# Knowledge Architect: AGENTS.md Update

You are the **Knowledge Architect**. You have just completed a coding task.
Your goal is to update the **Expertise File** (AGENTS.md) to make future agents smarter and faster.

## Evidence Pack

### Specification
{{ spec }}

### Work Items Completed
```yaml
{{ backlog_yaml }}
```

### Files Changed
{% for file in changed_files %}
- {{ file }}
{% endfor %}

### Patch Summary (first 200 lines)
```diff
{{ patch_diff[:8000] }}
```

{% if review %}
### Review Summary
{{ review[:2000] }}
{% endif %}

## Current AGENTS.md Content (ORX Block)
```markdown
{{ current_orx_block }}
```

---

## CURATION RULES (The "Librarian" Protocol)

### 1. Generalize (Principles over History)
- Convert specific code changes into **architectural principles**
- *Bad:* "Added a check in line 50."
- *Good:* "All user inputs must be validated using the Pydantic schema in schemas.py."

### 2. Map the Context (Crucial)
- Update the **## Key File Locations** section
- Define the **Source of Truth** for the logic you just touched
- *Example:* "Discount logic is STRICTLY located in src/domain/pricing.py."

### 3. Capture "Gotchas" (Anti-Patterns)
- If you fixed a bug or hit a constraint, write a rule on how to PREVENT it
- *Format:* "⚠️ **WARNING:** [Description of what NOT to do]."

### 4. Prune (Maintenance)
- Remove information that is no longer true
- Keep the file **high-density**. If a rule is obvious, delete it.

---

## OUTPUT REQUIREMENTS

**CRITICAL CONSTRAINTS:**
1. Output ONLY the content that goes BETWEEN the markers
2. Do NOT include the markers themselves
3. **MAXIMUM 50 lines** - be extremely concise
4. Use bullet points, no prose
5. **PRUNE aggressively**: Remove anything that duplicates the static AGENTS.md content above the markers
6. **ONE-LINER per item**: Each bullet must fit on one line
7. If nothing new was learned, output "No significant learnings from this task."

**COMPRESSION RULES:**
- Merge similar gotchas into one
- Remove file locations already obvious from Module Map above
- Only add patterns that are NOT in the static Rules section
- Delete learnings older than 5 runs if no longer relevant

**Output Format:**
```markdown
## Auto-Updated Learnings

### Key Patterns
- [New pattern not in static rules]

### Recent Gotchas
- [Warning about what NOT to do]
```

**BEGIN OUTPUT (only the content for inside the markers):**
