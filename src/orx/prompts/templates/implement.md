# Implementation Prompt

You are implementing a specific work item from the backlog.

## Task Summary

{{ task_summary }}

{% if spec_highlights %}
## Spec Highlights

{{ spec_highlights }}
{% endif %}

## Current Work Item

**ID**: {{ item_id }}
**Title**: {{ item_title }}
**Objective**: {{ item_objective }}

### Acceptance Criteria
{% for criterion in acceptance %}
- {{ criterion }}
{% endfor %}

### Files Hint
{% for file in files_hint %}
- {{ file }}
{% endfor %}

{% if file_snippets %}
## Relevant File Snippets

{% for snippet in file_snippets %}
### {{ snippet.path }}{% if snippet.truncated %} (truncated){% endif %}

```
{{ snippet.content }}
```
{% endfor %}
{% endif %}

## Instructions

1. Implement the work item according to the acceptance criteria
2. Create or update tests for the new functionality
3. Follow the project's coding standards

## Code Standards

- Use type hints everywhere
- Add docstrings with Google style
- Keep functions focused and small
- Handle errors appropriately
- Keep imports sorted (ruff I001) when adding new files

## Output

Apply your changes directly to the filesystem. Do not output code blocks - make the actual file changes.
Do not run tests or shell commands; the pipeline handles verification.

---

**Important**: Only make changes necessary for this work item. Do not refactor unrelated code.
