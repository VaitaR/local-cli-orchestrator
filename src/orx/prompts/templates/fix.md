# Fix Prompt

You are fixing issues found in the previous implementation attempt.

## Task Summary

{{ task_summary }}

{% if spec_highlights %}
## Spec Highlights

{{ spec_highlights }}
{% endif %}

{% if repo_context is defined and repo_context %}
## Repo Context

{{ repo_context }}
{% endif %}

{% if verify_commands is defined and verify_commands %}
## VERIFY Will Run

The pipeline will run these checks after your changes:

{{ verify_commands }}

Ensure your fixes pass all these gates.
{% endif %}

## Current Work Item

**ID**: {{ item_id }}
**Title**: {{ item_title }}
**Objective**: {{ item_objective }}
**Attempt**: {{ attempt }}

### Acceptance Criteria
{% for criterion in acceptance %}
- {{ criterion }}
{% endfor %}

{% if files_hint %}
### Files Hint
{% for file in files_hint %}
- {{ file }}
{% endfor %}
{% endif %}

{% if file_snippets %}
## Relevant File Snippets

{% for snippet in file_snippets %}
### {{ snippet.path }}{% if snippet.truncated %} (truncated){% endif %}

```
{{ snippet.content }}
```
{% endfor %}
{% endif %}

## Evidence of Failure

### Gate Results
{% if ruff_failed %}
**Ruff Check Failed**:
```
{{ ruff_log }}
```
{% endif %}

{% if pytest_failed %}
**Pytest Failed**:
```
{{ pytest_log }}
```
{% endif %}

{% if diff_empty %}
**No Changes Detected**: The previous attempt made no file changes. You must modify files to complete this task.
{% endif %}

{% if patch_diff %}
### Current Diff

```diff
{{ patch_diff }}
```
{% endif %}

## Instructions

1. Analyze the failure evidence above
2. Identify the root cause of the failure
3. Make targeted fixes to address the issues
4. Ensure all acceptance criteria are met
5. If a lint error is trivial (I001/UP/unused import), fix it immediately

## Common Issues

- **Ruff failures**: Fix syntax errors, import sorting, unused imports (keep imports ordered)
- **Pytest failures**: Fix failing assertions, missing fixtures, import errors
- **Empty diff**: Ensure you're actually modifying files, not just outputting code

## Output

Apply your fixes directly to the filesystem. Focus only on fixing the identified issues.
Do not run tests or shell commands; the pipeline handles verification.

---

**Important**: Make minimal changes to fix the issues. Do not refactor or add features.
