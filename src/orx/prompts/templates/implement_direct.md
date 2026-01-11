# Direct Implementation Prompt

You are implementing a task directly without prior planning or decomposition.

## Task

{{ task }}

{% if agents_context is defined and agents_context %}
## Development Guidelines (from AGENTS.md)

{{ agents_context }}

**MUST FOLLOW**:
- Module Boundaries: Never introduce cross-import cycles
- NOT TO DO: Avoid all listed anti-patterns
- Coding Patterns: Use established helpers
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

{% if error_logs is defined and error_logs %}
## Previous Errors

The following errors need to be fixed:

```
{{ error_logs }}
```
{% endif %}

## Instructions

1. **Analyze the task** to understand what needs to be done
2. **Identify affected files** using the repo structure
3. **Read files in batches**: Use ARCHITECTURE.md module map to identify ALL related files upfront. Read them together in one batch, not one-by-one.
4. **Implement the changes** according to the task description
5. **Create or update tests** as needed

**FILE READING STRATEGY** (CRITICAL):
- Identify the full file set needed upfront
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

## SELF-CHECK: Verify Your Changes Work

**YOU** are responsible for validating your code BEFORE completing this stage. Don't skip this!

### Step 1: Format and Lint Your Code

Run these commands to catch style issues early:

```bash
python -m ruff format .
python -m ruff check --fix .
python -m ruff check .  # Verify ALL issues are resolved
```

If ruff finds issues:
- Common issues: trailing whitespace (W293), unused imports (F401), import ordering (I001)
- Fix them manually or use ruff --fix
- Do NOT move to next step until `ruff check .` returns no errors

### Step 2: Run Tests

If your changes affect tested code:

```bash
python -m pytest tests/unit -v
```

If tests fail:
- Read the failure message
- Make targeted fixes
- Re-run tests
- Repeat until all tests pass

### Step 3: Final Verification Before Completion

**CRITICAL**: Before marking this stage complete, verify:

✓ `ruff check .` → No errors  
✓ No trailing whitespace in any modified files  
✓ All imports are used and properly ordered  
✓ All tests pass  
✓ All acceptance criteria met  

{% if verify_commands is defined and verify_commands %}
The pipeline will run: {{ verify_commands }}
Ensure these will pass before completing.
{% endif %}

**If verification fails, the pipeline will request changes and ask you to fix them.**

---

**Important**: Focus on what the task requires. Keep changes minimal and targeted.
