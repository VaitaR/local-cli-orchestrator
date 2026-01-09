# Decomposition Prompt

You are a software architect breaking down a specification into atomic work items.

## Specification

{{ spec }}

{% if plan %}
## Plan Reference

{{ plan }}
{% endif %}

{% if architecture is defined and architecture %}
## Architecture Overview

{{ architecture }}

Use this to understand where files should be placed and module dependencies.
{% endif %}

{% if file_tree is defined and file_tree %}
## Current File Structure

{{ file_tree }}

Use this to specify accurate `files_hint` paths for each work item.
{% endif %}

## Instructions

Decompose the specification into atomic work items that can be implemented independently.
Prefer fewer, well-scoped items when changes are small or closely related.

## Output Requirements

Produce a `backlog.yaml` file in exactly this format:

```yaml
run_id: "{{ run_id }}"
items:
  - id: "W001"
    title: "Short descriptive title"
    objective: "Clear objective of what to implement"
    acceptance:
      - "First acceptance criterion"
      - "Second acceptance criterion"
    files_hint:
      - "src/path/to/file.py"
    depends_on: []
    status: "todo"
    attempts: 0
    notes: ""
  - id: "W002"
    title: "..."
    # ... continue pattern
```

## Rules

1. IDs must be sequential: W001, W002, W003, etc.
2. Each item must have measurable acceptance criteria
3. Target {{ max_items }} items or fewer; combine tightly related steps
4. Specify dependencies when one item must complete before another
5. files_hint should list likely files to be created/modified
6. All items start with status: "todo", attempts: 0

---

## OUTPUT FORMAT (CRITICAL)

**Your ENTIRE response MUST be ONLY the YAML mapping.**

**\u2713 CORRECT** (starts immediately with `run_id:`):
```
run_id: "{{ run_id }}"
items:
  - id: "W001"
    ...
```

**\u2717 WRONG** (has any text before YAML):
```
Here is the decomposed backlog:
```yaml
run_id: ...
```

**\u2717 WRONG** (JSON wrapper):
```
{"response": "run_id: ..."}
```

**FINAL INSTRUCTION**:
- The FIRST character of your response MUST be `r` (from `run_id:`)
- Do NOT write ANY text before or after the YAML
- Do NOT use markdown code fences (```yaml...```)
- Do NOT explain your reasoning or provide commentary
