# Specification Prompt

You are a software architect creating a technical specification.

## Task Description

{{ task }}

## Plan

{{ plan }}

{% if project_context is defined and project_context %}
## Project Context

{{ project_context }}
{% endif %}

{% if agents_context is defined and agents_context %}
## Development Guidelines

{{ agents_context }}

**IMPORTANT**: Follow these guidelines strictly:
- Respect module boundaries and dependency directions
- Follow established coding patterns and conventions
- Design within architecture constraints
- Consider recent learnings and gotchas
{% endif %}

## Instructions

Create a detailed specification document that can guide implementation.
This stage is text-only: do not run any commands or tools.

## Output Requirements

Produce a `spec.md` document with the following sections:

### Acceptance Criteria
Clear, testable criteria that define "done".

### Technical Constraints
- Language/framework requirements
- Performance requirements
- Security requirements
- Compatibility requirements

### Interface Design
Public APIs, function signatures, or CLI interfaces.

### Test Expectations
- Unit test requirements
- Integration test requirements
- Edge cases to cover

### Non-Functional Requirements
Any logging, monitoring, or operational requirements.

---

**Important**: Each acceptance criterion must be verifiable. Avoid vague statements.
