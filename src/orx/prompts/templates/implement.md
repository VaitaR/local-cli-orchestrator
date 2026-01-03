# Implementation Prompt

You are implementing a specific work item from the backlog.

## Task Context

{{ task }}

## Specification

{{ spec }}

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

{% if project_map %}
## Project Map

{{ project_map }}
{% endif %}

## Instructions

1. Implement the work item according to the specification
2. Create or update tests for the new functionality
3. Follow the project's coding standards
4. Update project_map.md if you add new modules

## Code Standards

- Use type hints everywhere
- Add docstrings with Google style
- Keep functions focused and small
- Handle errors appropriately

## Output

Apply your changes directly to the filesystem. Do not output code blocks - make the actual file changes.

---

**Important**: Only make changes necessary for this work item. Do not refactor unrelated code.
