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

## Self-Reflection (Required)

At the very end of your response, YOU MUST output a JSON block wrapped in `<orx_meta>...</orx_meta>` tags. This block describes your confidence and any context gaps. It will be automatically stripped from artifacts.

Format:
```
<orx_meta>
{
  "confidence": 0.85,
  "context_gap": false,
  "missing_info": [],
  "tool_efficacy": "high",
  "reasoning_summary": "Brief one-sentence summary of your approach"
}
</orx_meta>
```

Field definitions:
- **confidence** (float 0.0-1.0): How confident you are in your solution.
- **context_gap** (bool): Set to `true` if you lacked important context.
- **missing_info** (list[str]): What was missing, if `context_gap` is true.
- **tool_efficacy** ("high"/"medium"/"low"): How helpful the available tools were.
- **reasoning_summary** (string): One sentence explaining your approach.

This metadata is critical for the orchestrator to assess output quality and improve future runs. Always include it, even if confidence is high.
