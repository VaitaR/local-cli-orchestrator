# System Context

This section contains static project context that does not change between pipeline stages.

{% if agents_context is defined and agents_context %}
## Development Guidelines (from AGENTS.md)

{{ agents_context }}

**IMPORTANT**: Follow these guidelines strictly:
- Respect module boundaries and dependency directions
- Follow established coding patterns and conventions
- Consider architecture constraints
- Review recent learnings for common pitfalls
{% endif %}

{% if architecture_overview is defined and architecture_overview %}
## Architecture Overview

{{ architecture_overview }}
{% endif %}

{% if architecture is defined and architecture %}
## Architecture

{{ architecture }}
{% endif %}

{% if project_context is defined and project_context %}
## Project Context

{{ project_context }}
{% endif %}

{% if repo_context is defined and repo_context %}
## Repository Context

{{ repo_context }}
{% endif %}

{% if verify_commands is defined and verify_commands %}
## Verification Commands

The pipeline will run these checks after changes:

{{ verify_commands }}

Ensure code passes all these gates.
{% endif %}

{% if definition_of_done is defined and definition_of_done %}
## Definition of Done

{{ definition_of_done }}
{% endif %}
