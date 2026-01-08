# Decomposition Prompt

You are a software architect breaking down a specification into atomic work items.

## Specification

{{ spec }}

{% if plan %}
## Plan Reference

{{ plan }}
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

**Important**: Output ONLY the YAML content, no additional commentary.
