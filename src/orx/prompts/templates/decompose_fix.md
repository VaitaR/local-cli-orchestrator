# Decomposition Fix Prompt

You previously produced invalid `backlog.yaml`. Fix it and return a valid YAML
mapping that follows the required schema exactly.

## Validation Error

{{ error }}

## Invalid Output (for reference only)

{{ invalid_output }}

## Required Output Format

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
```

## Rules

1. IDs must be sequential: W001, W002, W003, etc.
2. Each item must have measurable acceptance criteria.
3. Target {{ max_items }} items or fewer; combine tightly related steps.
4. Specify dependencies when one item must complete before another.
5. files_hint should list likely files to be created/modified.
6. All items start with status: "todo", attempts: 0.

---

**Important**:
- Output ONLY the YAML mapping.
- Do NOT use Markdown, bullet lists, or code fences.
- No extra commentary or headers.
