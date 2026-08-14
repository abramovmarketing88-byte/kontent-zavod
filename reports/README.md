# Run reports

После каждого `--once` завод пишет:

- `reports/last-run.md` / `reports/last-run.json` — последний прогон (без секретов)
- `reports/history/` — архив
- `logs/runs/<id>.log` — полный лог прогона

При ошибке файл `last-run.md` уходит в Telegram как документ.

Если на сервере есть write-доступ к GitHub (`GITHUB_TOKEN` или write deploy key),
скрипт `scripts/publish_run_report.sh` пушит отчёт в ветку **`run-reports`**.
Cloud Agent читает так:

```bash
git fetch origin run-reports
git show origin/run-reports:reports/last-run.md
```
