# Implementation Prompt

You are implementing a specific work item from the backlog.

## Task Summary

{{ task_summary }}

{% if spec_highlights %}
## Spec Highlights

{{ spec_highlights }}
{% endif %}

{% if repo_context is defined and repo_context %}
## Repo Context

{{ repo_context }}

**CRITICAL GUIDELINES**: If AGENTS.md or ARCHITECTURE.md are included above:
- **Module Boundaries**: Never introduce cross-import cycles. Check dependency direction rules.
- **Coding Patterns**: Follow established patterns (e.g., CommandRunner for subprocess, ContextPack for file I/O).
- **Testing**: Add tests for every stage and resume behavior per AGENTS.md.
- **Recent Learnings**: Review auto-updated learnings section for gotchas and best practices.
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
- Look at "Files Hint" + ARCHITECTURE.md module map → identify the full file set
- Read ALL needed files in ONE batch call (e.g., `read_file` with multiple paths or `grep_search`)
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
