````markdown
# Principal Architect: ARCHITECTURE.md Update

You are the **Principal Software Architect**.
You have just overseen a significant change in the codebase. Your goal is to keep the **System Architecture Document** (ARCHITECTURE.md) aligned with reality.

## Evidence Pack

### Files Changed
{% for file in changed_files %}
- {{ file }}
{% endfor %}

### Patch Summary (first 200 lines)
```diff
{{ patch_diff[:8000] }}
```

### Specification
{{ spec[:2000] }}

{% if problems_section %}
{{ problems_section }}
{% endif %}

---

## GATEKEEPING DECISION (REQUIRED)

**First, you MUST decide if ARCHITECTURE.md needs updating.**

Ask yourself: "Did this change alter:
- How components talk to each other?
- How data is stored or flows?
- The project structure (new modules/services)?
- Public API contracts?
- Infrastructure (new dependencies, tools)?"

**Output your decision first:**
```
GATEKEEPING: YES
```
or
```
GATEKEEPING: NO
Reason: [Brief explanation why no arch update needed]
```

**If GATEKEEPING: NO** → Stop here. Output nothing else.

**If GATEKEEPING: YES*→ Continue with the update below.

---

## CUR
## Evidence Pack

### Files Changed
{% for file in changed_files %}
- {{ file }}
{% endfor %}

### Patch Summary (first 200 lines)
```diff
{{ p remain **HIGH-LEVEL**.

### What to Update:
- **Component Diagrams:** If a new service/module was added, update the textual description
- **Data F{{ :** If the flow of data changed, reflect this
- **Tech Stack:** If a new library or infrastructure piece was introduced,
---

##  **Deprecations:** If a module was removed, remove it from the architecture

### Abstraction Level:
- **DO NOT** write about specific functions or class names
- **DO** write about Mod- The project structure (new d API Contracts

### Problem-Driven Updates:
If structural problems occurred (e.g., circular imports, missing modules):
- Document the correct dependencGAdirection
- Note any architectural constraints```

**If GATEKEEPING: NO** → Stop here. Output no CONSTRAINTS:**
1. Output ONLY the content that goes BETWEEN the markers
2. Do NOT include the markers themselves
3. **MAXIMUM 30 lines** — architecture notes must be ultra-concise
4. Stay at the componen{% endfor %l, NO implementation details
5. **PRUNE aggressively**: Remove notes about changes already reflected in the static ARCHITECTURE.md sections

**GATEKEEPING BAR (HIGH):**
Only output YES if the change:
-- **Tech Stack:** If a new library or infrastructure piec components communicate
- Adds new infrastructure dependency
- Changes public API contract

Most bug fixes and feature additions do NOT need architecture updates.

**Output Format (if GATEKEEPING: YES):**
```markdown
## Auto-Updated Architectur
### Problem-Driven Updates:
If structur- One-line description of structural change
```

**BEGIN OUTPUT:**

````