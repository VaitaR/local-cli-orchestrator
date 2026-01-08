# Decomposition Fix Prompt

**CRITICAL**: You previously produced invalid `backlog.yaml`. You MUST fix it now.

## What Went Wrong

{{ error }}

## Your Previous Output (DO NOT REPEAT THIS)

{{ invalid_output }}

---

## What You MUST Do Now

1. **Analyze the error** - Understand what was wrong
2. **Produce ONLY valid YAML** - No explanations, no markdown, no JSON wrapper
3. **Start output with `run_id:`** - This is the first line of valid YAML

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

## OUTPUT REQUIREMENTS (MANDATORY)

**✓ CORRECT OUTPUT** (starts immediately with YAML):
```
run_id: "{{ run_id }}"
items:
  - id: "W001"
    title: "..."
```

**✗ WRONG OUTPUT** (has explanations/wrappers):
```
I've analyzed the error and here's the corrected YAML:
```yaml
run_id: "{{ run_id }}"
```

**✗ WRONG OUTPUT** (JSON wrapper):
```
{"response": "run_id: ..."}
```

**✗ WRONG OUTPUT** (explanatory text):
```
Let me fix the YAML for you. The issue was...
```

---

**FINAL INSTRUCTION**: Your ENTIRE response must be ONLY the YAML mapping.
The FIRST character of your response MUST be `r` (from `run_id`).
Do NOT write ANY text before or after the YAML.
Do NOT use markdown code fences.
If you cannot produce valid YAML, output EXACTLY: `ERROR: CANNOT_FIX`
