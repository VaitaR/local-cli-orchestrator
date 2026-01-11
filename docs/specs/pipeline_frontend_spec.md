# Pipeline Frontend Specification v1.0

## Overview

This specification defines the frontend implementation for pipeline management in the Orx dashboard. Users can view, select, modify, and create pipelines directly from the web UI.

## User Stories

1. **As a user**, I want to select a predefined pipeline when starting a run
2. **As a user**, I want to see what nodes/stages a pipeline contains
3. **As a user**, I want to create a new custom pipeline based on an existing one
4. **As a user**, I want to modify pipeline nodes on-the-fly before starting a run
5. **As a user**, I want to save my custom pipeline for future use

## UI Components

### 1. Pipeline Selector (in Start Run Form)

Located in the start run modal, allows selecting from available pipelines:

```
┌─────────────────────────────────────────────────┐
│ 🔧 Pipeline                                     │
│ ┌─────────────────────────────────────────────┐│
│ │ ▼ standard - Standard Full Pipeline         ││
│ └─────────────────────────────────────────────┘│
│ [✎ Customize] [+ Create New]                   │
└─────────────────────────────────────────────────┘
```

Options:
- `standard` (default) - Full planning flow
- `fast_fix` - Skip planning, direct implementation
- `plan_only` - Generate plan without implementation
- Custom pipelines from ~/.orx/pipelines/

### 2. Pipeline Preview Panel

Shows nodes in selected pipeline:

```
┌─────────────────────────────────────────────────┐
│ Pipeline: standard (6 nodes)                    │
│─────────────────────────────────────────────────│
│ 1. 📝 plan [llm_text]                          │
│    └─ Inputs: task, repo_map, agents_context   │
│ 2. 📋 spec [llm_text]                          │
│    └─ Inputs: task, plan, repo_map             │
│ 3. 🔀 decompose [llm_text]                     │
│    └─ Inputs: spec, repo_map, architecture     │
│ 4. ⚙️ implement_loop [map]                     │
│    └─ Inputs: backlog, spec, agents_context    │
│ 5. 🔍 review [llm_text]                        │
│    └─ Inputs: plan, patch_diff, backlog        │
│ 6. 🚀 ship [custom]                            │
│    └─ Inputs: review, patch_diff               │
└─────────────────────────────────────────────────┘
```

### 3. Pipeline Editor Modal

For creating/modifying pipelines:

```
┌─────────────────────────────────────────────────┐
│ ✏️ Edit Pipeline: my_custom                     │
│─────────────────────────────────────────────────│
│ Name: [My Custom Pipeline          ]            │
│ Description: [Custom flow for bugfixes...]      │
│─────────────────────────────────────────────────│
│ Nodes:                                          │
│ ┌─────────────────────────────────────────────┐│
│ │ ☰ 1. plan [llm_text] [✎] [🗑]               ││
│ │ ☰ 2. implement [llm_apply] [✎] [🗑]         ││
│ │ ☰ 3. verify [gate] [✎] [🗑]                 ││
│ └─────────────────────────────────────────────┘│
│ [+ Add Node]                                    │
│─────────────────────────────────────────────────│
│ [Cancel] [Save as New] [Save]                   │
└─────────────────────────────────────────────────┘
```

### 4. Node Editor (Inline)

When editing a node:

```
┌─────────────────────────────────────────────────┐
│ Node: plan                                      │
│─────────────────────────────────────────────────│
│ ID: [plan]                                      │
│ Type: [▼ llm_text]                             │
│ Template: [plan.md]                             │
│ Inputs: [task] [repo_map] [agents_context] [+]  │
│ Outputs: [plan] [+]                             │
│─────────────────────────────────────────────────│
│ ⚙️ Config:                                      │
│ Model: [▼ Default]                             │
│ Timeout: [600] sec                              │
│ Gates: [] (for gate nodes)                      │
│─────────────────────────────────────────────────│
│ [Cancel] [Apply]                                │
└─────────────────────────────────────────────────┘
```

## API Endpoints

### GET /api/pipelines
Returns list of available pipelines.

Response:
```json
{
  "pipelines": [
    {
      "id": "standard",
      "name": "Standard Full Pipeline",
      "description": "Plan → Spec → Decompose → Implement → Review → Ship",
      "builtin": true,
      "node_count": 6,
      "nodes": [
        {"id": "plan", "type": "llm_text", "template": "plan.md"},
        ...
      ]
    }
  ]
}
```

### GET /api/pipelines/{id}
Get full pipeline definition.

### POST /api/pipelines
Create new pipeline.

### PUT /api/pipelines/{id}
Update existing pipeline.

### DELETE /api/pipelines/{id}
Delete custom pipeline.

### GET /api/node-types
Get available node types and their config schemas.

Response:
```json
{
  "node_types": [
    {
      "value": "llm_text",
      "label": "LLM Text Generation",
      "description": "Generate text output via LLM",
      "requires_template": true,
      "config_schema": {...}
    },
    {
      "value": "llm_apply",
      "label": "LLM Apply (Filesystem)",
      "description": "Apply filesystem changes via LLM",
      "requires_template": true
    },
    {
      "value": "map",
      "label": "Map (Parallel)",
      "description": "Process items in parallel",
      "requires_template": false
    },
    {
      "value": "gate",
      "label": "Gate (Verification)",
      "description": "Run quality gates",
      "requires_template": false,
      "config_schema": {"gates": ["ruff", "pytest", ...]}
    },
    {
      "value": "custom",
      "label": "Custom Function",
      "description": "Execute custom Python function",
      "requires_template": false
    }
  ]
}
```

### GET /api/context-blocks
Get available context blocks for node inputs.

## Data Flow

1. User opens Start Run modal
2. Frontend fetches `/api/pipelines` and `/api/context-blocks`
3. User selects pipeline → preview shows nodes
4. User clicks "Customize" → Pipeline editor opens with copy
5. User modifies nodes (drag-drop reorder, add, remove, edit)
6. User clicks "Save as New" → POST to `/api/pipelines`
7. User clicks "Start Run" → request includes `pipeline` field

## State Management

Frontend uses sessionStorage for:
- `orx_pipelines_cache` - Cached pipeline list
- `orx_current_pipeline_edit` - Currently edited pipeline (for restore)

## Styling

Pipeline components follow existing dashboard styles:
- Use CSS variables from base.html
- Cards use `.card` class
- Forms use `.form-group` class
- Buttons use `.btn`, `.btn-primary`, `.btn-secondary`

## Node Type Icons

| Type | Icon |
|------|------|
| llm_text | 📝 |
| llm_apply | ⚙️ |
| map | 🔀 |
| gate | ✓ |
| custom | 🔧 |

## Implementation Phases

### Phase 1: Basic Selection (MVP)
- Pipeline dropdown in start form
- Pipeline preview (read-only)
- Pass pipeline ID to API

### Phase 2: On-the-fly Modification
- Clone pipeline for editing
- Add/remove/reorder nodes
- Modify node config
- Save as temporary (single use)

### Phase 3: Full Management
- Create new pipelines
- Edit existing custom pipelines
- Delete custom pipelines
- Import/export YAML

## Error Handling

- Show validation errors inline
- Prevent invalid configurations
- Confirm before deleting pipelines
- Auto-save draft to sessionStorage
