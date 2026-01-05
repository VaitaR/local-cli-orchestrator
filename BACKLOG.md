# ORX Backlog

## Speed and Cost
- Enforce text-only execution for plan/spec/review (disable tool usage entirely).
- Shrink implement context to AC + file shortlist + targeted snippets + diff/evidence only.
- Run full verify once per run (pre-ship) while keeping fast per-item verify.
- Add batching option to implement multiple backlog items in one apply pass.

## Observability
- Add `orx audit` command to summarize events.jsonl, gates, and LLM timings.
- Record LLM invocation durations/usage per stage in metrics.

## Reliability
- Add fix-loop stop conditions for no-diff or repeated identical failures.
- Improve gate triage artifacts (structured errors.md + machine-readable triage.json).
