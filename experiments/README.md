# Experiments

This folder is for local, disposable experiment artifacts (A/B runs, logs, diffs).

Contract:
- Treat experiment subfolders as local-only scratch space.
- Keep metrics locally for analysis; `experiments/**/metrics/**` is gitignored.
- If a result must be shared, summarize it in docs or export a short report.
