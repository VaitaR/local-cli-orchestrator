# Implementation Prompt

You are implementing a specific work item from the backlog.

## Task Summary

{{ task_summary }}

{% if spec_highlights %}
## Spec Highlights

{{ spec_highlights }}
{% endif %}

{% if agents_context is defined and agents_context %}
## Development Guidelines (from AGENTS.md)

{{ agents_context }}

**MUST FOLLOW**:
- Module Boundaries: Never introduce cross-import cycles
- NOT TO DO: Avoid all listed anti-patterns
- Coding Patterns: Use established helpers (CommandRunner, ContextPack, etc.)
{% endif %}

{% if repo_context is defined and repo_context %}
## Repo Context

{{ repo_context }}
{% endif %}

{% if verify_commands is defined and verify_commands %}
## VERIFY Will Run

The pipeline will run these checks after your changes:

{{ verify_commands }}

Ensure your code passes all these gates.
{% endif %}

## Current Work Item

**ID**: {{ item_id }}
**Title**: {{ item_title }}
**Objective**: {{ item_objective }}
{% if item_notes %}
**Notes (FAILURE EVIDENCE / FEEDBACK)**:
{{ item_notes }}
{% endif %}

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

1. **Read files in batches**: Use ARCHITECTURE.md module map to identify ALL related files upfront. Read them together in one batch, not one-by-one.
2. Implement the work item according to the acceptance criteria
3. Create or update tests for the new functionality
4. Follow the project's coding standards

**FILE READING STRATEGY** (CRITICAL):
- Look at "Files Hint" + module map → identify the full file set
- Read ALL needed files in ONE batch call
- Do NOT read files one at a time in separate tool calls
- For related modules, read the whole directory at once

## Code Standards

- Use type hints everywhere
- Add docstrings with Google style
- Keep functions focused and small
- Handle errors appropriately
- **Import ordering (ruff I001)**: Standard library → third-party → local. Alphabetical within groups. Use `from __future__ import annotations` first.
- **No unused imports (ruff F401)**: Only import what you use.
- **No trailing whitespace (ruff W293)**: Keep blank lines truly empty.
- When adding new files, ensure they have proper `__init__.py` exports if needed.

## Output

Apply your changes directly to the filesystem. Do not output code blocks - make the actual file changes.
Do not run tests or shell commands; the pipeline handles verification.

---

**Important**: Only make changes necessary for this work item. Do not refactor unrelated code.
