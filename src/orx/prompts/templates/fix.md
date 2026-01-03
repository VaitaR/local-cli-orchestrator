# Fix Prompt

You are fixing issues found in the previous implementation attempt.

## Task Context

{{ task }}

## Specification

{{ spec }}

## Current Work Item

**ID**: {{ item_id }}
**Title**: {{ item_title }}
**Objective**: {{ item_objective }}
**Attempt**: {{ attempt }}

### Acceptance Criteria
{% for criterion in acceptance %}
- {{ criterion }}
{% endfor %}

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

## Common Issues

- **Ruff failures**: Fix syntax errors, import sorting, unused imports
- **Pytest failures**: Fix failing assertions, missing fixtures, import errors
- **Empty diff**: Ensure you're actually modifying files, not just outputting code

## Output

Apply your fixes directly to the filesystem. Focus only on fixing the identified issues.

---

**Important**: Make minimal changes to fix the issues. Do not refactor or add features.
