# Run reports

После каждого `--once` завод пишет:

- `reports/last-run.md` / `reports/last-run.json` — последний прогон (без секретов)
- `reports/last-10.md` — индекс **последних 10** прогонов (статус, ошибка, хвост лога)
- `reports/AGENT.md` — куда смотреть агенту
- `reports/diagnose.md` — снимок здоровья VPS (`scripts/diagnose.sh`)
- `reports/history/<run_id>.md` — полные отчёты (хранятся ≤10)
- `logs/runs/<id>.log` — полный лог прогона (тоже ≤10)

При ошибке файл `last-run.md` уходит в Telegram как документ.
При падении run-once автоматически вызывается `diagnose.sh`.

Если на сервере есть write-доступ к GitHub (`GITHUB_TOKEN` или write deploy key),
скрипт `scripts/publish_run_report.sh` пушит отчёты в ветку **`run-reports`**.

Cloud Agent / Cursor — **сначала** читай:

```bash
git fetch origin run-reports
git show origin/run-reports:reports/last-10.md
git show origin/run-reports:reports/last-run.md
# при необходимости:
git show origin/run-reports:reports/history/<run_id>.md
```
