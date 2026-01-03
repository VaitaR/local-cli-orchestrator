# Review Prompt

You are reviewing the completed implementation.

## Specification

{{ spec }}

## Changes Made

```diff
{{ patch_diff }}
```

{% if gate_results %}
## Gate Results

{% for gate in gate_results %}
- **{{ gate.name }}**: {{ "PASSED" if gate.ok else "FAILED" }} - {{ gate.message }}
{% endfor %}
{% endif %}

## Instructions

Review the changes and produce two outputs **in your response text** (DO NOT create files in the worktree):

1. `review.md` - Detailed code review
2. `pr_body.md` - Concise PR description

**CRITICAL**: Do NOT create files in the worktree. Output the content directly in your response.

## Output Format

### review.md

```markdown
# Code Review

## Summary
Brief summary of what was implemented.

## Observations
Key observations about the implementation.

## Code Quality
Assessment of code quality, style, and best practices.

## Test Coverage
Assessment of test coverage.

## Recommendations
Any recommendations for future improvements (not blockers).

## Verdict
APPROVED / CHANGES_REQUESTED
```

### pr_body.md

```markdown
## Summary
One paragraph summary of changes.

## Changes
- Bullet list of key changes

## Testing
How the changes were tested.
```

---

**Important**: Be constructive. Focus on significant issues, not nitpicks.
