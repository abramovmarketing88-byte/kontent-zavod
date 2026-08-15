# Agent lookup — Kontent Zavod runs

Always inspect these before guessing:

1. `reports/last-run.md` — newest full report + log tail
2. `reports/last-10.md` — index of the last 10 iterations
3. `reports/history/<run_id>.md` — full report for a past run
4. `reports/diagnose.md` — VPS health (if present)

On GitHub (after VPS publish):

```bash
git fetch origin run-reports
git show origin/run-reports:reports/last-10.md
git show origin/run-reports:reports/last-run.md
```
