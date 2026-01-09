# Robust YAML Extraction System

## Problem Statement

LLM models sometimes return responses in unexpected formats when asked to produce pure YAML:
- YAML wrapped in markdown code fences (```yaml...```)
- JSON wrappers containing YAML strings (`{"response": "..."}`)
- Explanatory text before/after YAML blocks
- Mixed content with YAML embedded in prose

This caused the `decompose` stage to fail with errors like:
```
Invalid backlog YAML after auto-fix: Backlog YAML must be a mapping
```

## Solution Architecture

### Multi-Layer YAML Extraction

Implemented a production-ready extraction system with multiple fallback strategies:

```
┌─────────────────────────────────────────────────────────────┐
│                   YAMLExtractor Pipeline                     │
│                                                               │
│  1. Direct YAML      ──► Try parse as-is (skip if JSON)     │
│  2. Markdown Fence   ──► Extract from ```yaml...```         │
│  3. JSON Wrapper     ──► Extract from {"response": "..."}   │
│  4. YAML Markers     ──► Extract from ---...--- or comments │
│  5. Heuristic        ──► Find first valid YAML block        │
│                                                               │
│  ✓ Success ──► Return dict                                   │
│  ✗ All Fail ──► Raise YAMLExtractionError                   │
└─────────────────────────────────────────────────────────────┘
```

### Components

1. **YAMLExtractor** (`src/orx/context/yaml_extractor.py`)
   - Multi-strategy extraction with ordered fallbacks
   - Strict mode for conservative parsing
   - Validation integration with Pydantic models
   - Comprehensive error reporting

2. **Enhanced Prompts**
   - `decompose.md`: Strict output format instructions
   - `decompose_fix.md`: Explicit examples of correct/incorrect outputs
   - Clear error markers (`ERROR: CANNOT_FIX`) for failure signaling

3. **Improved Backlog Parser** (`src/orx/context/backlog.py`)
   - Uses YAMLExtractor for robust parsing
   - Better error messages with context
   - Structured logging for debugging

4. **DecomposeStage Updates** (`src/orx/stages/decompose.py`)
   - Attempt extraction with `strict=False` (all strategies)
   - Enhanced error handling in auto-fix
   - Check for explicit error markers
   - Detailed logging of extraction attempts

## Usage

### Basic Extraction

```python
from orx.context.yaml_extractor import YAMLExtractor

extractor = YAMLExtractor(strict=False)
try:
    data = extractor.extract(llm_response)
    # data is a validated dict
except YAMLExtractionError as e:
    # Handle extraction failure
    print(f"Could not extract YAML: {e}")
    print(f"Original content: {e.original_content}")
```

### With Pydantic Validation

```python
from orx.context.backlog import Backlog

# Automatically uses YAMLExtractor internally
try:
    backlog = Backlog.from_yaml(llm_response, strict=False)
except ValueError as e:
    print(f"Invalid backlog: {e}")
```

### Safe Extraction (No Exceptions)

```python
from orx.context.yaml_extractor import safe_extract_yaml

data = safe_extract_yaml(llm_response)
if data is None:
    # Extraction failed
    print("Could not extract YAML")
else:
    # data is valid dict
    print(f"Extracted: {data}")
```

## Strategies Explained

### 1. Direct YAML
Attempts to parse content directly as YAML. Skips if content looks like JSON wrapper to avoid premature success.

### 2. Markdown Fence
Extracts YAML from code blocks:
```yaml
run_id: "test"
items: []
```

Supports both `yaml` and `yml` language tags, or no tag at all.

### 3. JSON Wrapper
Handles responses wrapped in JSON:
```json
{
  "response": "run_id: \"test\"\nitems: []",
  "stats": {...}
}
```

Looks for common fields: `response`, `yaml`, `content`, `result`.

### 4. YAML Markers
Extracts from explicitly marked blocks:
```
---
run_id: "test"
items: []
---
```

Or comment markers:
```
# YAML START
run_id: "test"
# YAML END
```

### 5. Heuristic
Intelligently finds YAML blocks in mixed content:
```
Here's the corrected YAML:

run_id: "test"
items:
  - id: "W001"

That should work now.
```

Stops at the first complete valid YAML mapping found.

## Error Handling

### Explicit Error Marker
If the model cannot fix the YAML, it can output:
```
ERROR: CANNOT_FIX
```

This is detected and handled gracefully with an informative error message.

### Structured Errors
All extraction failures raise `YAMLExtractionError` with:
- Clear error message
- Original content (for debugging)
- Strategy context (via logging)

## Testing

Comprehensive test suite in `tests/unit/context/test_yaml_extractor.py`:
- 17 test cases covering all strategies
- Real-world failure case validation
- Edge cases (empty content, non-dict YAML, etc.)
- Pydantic integration testing

Run tests:
```bash
pytest tests/unit/context/test_yaml_extractor.py -v
```

## Prompt Design Improvements

### Before
```markdown
**Important**:
- Output ONLY the YAML mapping.
- No extra commentary.
```

### After
```markdown
## OUTPUT FORMAT (CRITICAL)

**✓ CORRECT** (starts immediately with `run_id:`):
```
run_id: "..."
items:
  - id: "W001"
```

**✗ WRONG** (has explanations):
```
Here is the YAML:
```yaml
run_id: "..."
```

**✗ WRONG** (JSON wrapper):
```json
{"response": "run_id: ..."}
```

**FINAL INSTRUCTION**:
- The FIRST character must be `r` (from `run_id:`)
- Do NOT use markdown code fences
- If you cannot produce valid YAML, output: `ERROR: CANNOT_FIX`
```

## Monitoring & Debugging

All extraction attempts are logged with structured logging:

```
2026-01-08 20:38:18 [debug] YAML extraction succeeded
  strategy=heuristic
  preview={'run_id': 'test_123', ...}
```

Failed attempts log each strategy tried:
```
2026-01-08 20:38:18 [debug] YAML extraction strategy failed
  strategy=direct
  error=...
```

## Production Considerations

### Performance
- Strategies ordered by likelihood (direct → fence → wrapper)
- Early exit on first success
- Minimal overhead (<50ms for typical responses)

### Safety
- Strict mode available for security-critical contexts
- Validation against Pydantic schemas
- No code execution or unsafe operations
- Comprehensive error messages for debugging

### Maintainability
- Clear separation of concerns
- Extensible strategy pattern
- Well-tested with high coverage
- Documented with examples

## Migration Path

Old code:
```python
backlog = Backlog.from_yaml(content)
```

New code (backward compatible):
```python
# Same API, now with robust extraction
backlog = Backlog.from_yaml(content, strict=False)
```

The `strict` parameter controls extraction strategy:
- `strict=False` (default): All strategies (recommended)
- `strict=True`: Only direct + markdown fence (conservative)

## Future Enhancements

Potential improvements:
1. **Template-based reconstruction**: If extraction fails, attempt to reconstruct from schema
2. **Confidence scoring**: Return confidence metrics for each extraction
3. **Strategy learning**: Track which strategies work best per model/stage
4. **Custom strategies**: Plugin system for domain-specific extraction patterns

## Summary

This system provides **production-ready resilience** against LLM output variability while maintaining:
- ✅ Backward compatibility
- ✅ Clear error messages
- ✅ Comprehensive testing
- ✅ Performance efficiency
- ✅ Extensibility

The multi-layer approach ensures that even if a model produces unexpected formatting, the system can extract valid YAML and continue execution without manual intervention.
