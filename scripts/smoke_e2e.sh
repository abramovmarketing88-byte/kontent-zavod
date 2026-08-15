#!/usr/bin/env bash
# Predictable e2e: put one YouTube Shorts URL in inbox and run pipeline once.
set -euo pipefail
ROOT="${PROJECT_ROOT:-/opt/kontent-zavod}"
cd "$ROOT"
mkdir -p inbox output jobs data logs reports inbox/processed

URL="${1:-https://www.youtube.com/shorts/jNQXAC9IVRw}"
echo "# smoke e2e $(date -Is)" > inbox/urls.txt
echo "$URL" >> inbox/urls.txt

echo "Smoke URL: $URL"
bash scripts/run_once.sh
code=$?

echo "---- last-run.md (head) ----"
head -n 40 reports/last-run.md 2>/dev/null || echo '(no report)'
echo "---- status ----"
if [ -f reports/last-run.md ] && grep -q 'status: \*\*ok\*\*' reports/last-run.md; then
  echo "SMOKE_OK"
  exit 0
fi
echo "SMOKE_FAILED exit=$code (see reports/last-run.md)"
exit "${code:-1}"
