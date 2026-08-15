#!/bin/bash
# Push last-run + last-10 history to branch run-reports so Cloud Agents can diagnose.
# Needs write access: deploy key with write OR GITHUB_TOKEN in .env
set -euo pipefail
cd /opt/kontent-zavod
mkdir -p reports logs reports/history

if [ ! -f reports/last-run.md ]; then
  echo "no reports/last-run.md — skip publish"
  exit 0
fi

REPORTS_GIT_PUSH=true
GITHUB_TOKEN=""
if [ -f .env ]; then
  # parse only needed keys (avoid sourcing whole .env with special chars)
  REPORTS_GIT_PUSH=$(grep -E '^REPORTS_GIT_PUSH=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
  REPORTS_GIT_PUSH=${REPORTS_GIT_PUSH:-true}
  GITHUB_TOKEN=$(grep -E '^GITHUB_TOKEN=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
fi

if [ "${REPORTS_GIT_PUSH}" = "false" ]; then
  echo "REPORTS_GIT_PUSH=false — local report only"
  exit 0
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

cp reports/last-run.md "$WORK/"
cp reports/last-run.json "$WORK/" 2>/dev/null || true
cp reports/last-10.md "$WORK/" 2>/dev/null || true
cp reports/AGENT.md "$WORK/" 2>/dev/null || true
cp reports/diagnose.md "$WORK/" 2>/dev/null || true
mkdir -p "$WORK/history"
# newest 10 history markdown + json
ls -1t reports/history/*.md 2>/dev/null | head -10 | while read -r f; do
  cp "$f" "$WORK/history/" 2>/dev/null || true
  j="${f%.md}.json"
  [ -f "$j" ] && cp "$j" "$WORK/history/" || true
done

URL=$(git -C /opt/kontent-zavod remote get-url origin)
if [ -n "${GITHUB_TOKEN}" ]; then
  URL="https://x-access-token:${GITHUB_TOKEN}@github.com/abramovmarketing88-byte/kontent-zavod.git"
fi

(
  cd "$WORK"
  git init -q
  git checkout -q -b run-reports
  git remote add origin "$URL"
  mkdir -p reports/history
  mv last-run.md reports/
  [ -f last-run.json ] && mv last-run.json reports/ || true
  [ -f last-10.md ] && mv last-10.md reports/ || true
  [ -f AGENT.md ] && mv AGENT.md reports/ || true
  [ -f diagnose.md ] && mv diagnose.md reports/ || true
  if [ -d history ] && ls history/* >/dev/null 2>&1; then
    mv history/* reports/history/ || true
  fi
  git add reports
  git -c user.name="kontent-zavod" -c user.email="reports@kontent-zavod.local" \
    commit -qm "report: $(date -u +%Y-%m-%dT%H:%M:%SZ) (last-10)"
  if git push -f origin run-reports; then
    echo "$(date -Is) published run-reports (last-10)" >> /opt/kontent-zavod/logs/reports.log
  else
    echo "$(date -Is) publish FAILED (need write deploy key or GITHUB_TOKEN)" >> /opt/kontent-zavod/logs/reports.log
    exit 0
  fi
)
