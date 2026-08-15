# Agent notes — Kontent Zavod

When the user asks what went wrong with a run / Telegram failure / bad video:

1. **Fetch published reports** (VPS pushes after each run-once):
   ```bash
   git fetch origin run-reports
   git show origin/run-reports:reports/last-10.md
   git show origin/run-reports:reports/last-run.md
   ```
2. Read `reports/last-10.md` (index of last 10 iterations) then the matching
   `reports/history/<run_id>.md` for the failing run.
3. Do **not** guess from chat screenshots alone if these files are available.

Local paths after a run: `reports/last-run.md`, `reports/last-10.md`, `reports/AGENT.md`.

## YouTube Shorts upload
Needs OAuth (`YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN`), not `YOUTUBE_API_KEY`.
Trigger: `triggers/youtube-upload-once.id` → `scripts/check_youtube_upload.sh`.
Or: `docker compose run --rm worker python -m src.publish.youtube`
