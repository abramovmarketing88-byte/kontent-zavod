#!/bin/bash
# Push reports/last-run.md to branch run-reports so Cloud Agents can read failures.
# Needs write access: deploy key with write OR GITHUB_TOKEN in .env
set -euo pipefail
cd /opt/kontent-zavod
mkdir -p reports logs

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

URL=$(git -C /opt/kontent-zavod remote get-url origin)
if [ -n "${GITHUB_TOKEN}" ]; then
  URL="https://x-access-token:${GITHUB_TOKEN}@github.com/abramovmarketing88-byte/kontent-zavod.git"
fi

(
  cd "$WORK"
  git init -q
  git checkout -q -b run-reports
  git remote add origin "$URL"
  mkdir -p reports
  mv last-run.md reports/
  [ -f last-run.json ] && mv last-run.json reports/ || true
  git add reports
  git -c user.name="kontent-zavod" -c user.email="reports@kontent-zavod.local" \
    commit -qm "report: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if git push -f origin run-reports; then
    echo "$(date -Is) published run-reports" >> /opt/kontent-zavod/logs/reports.log
  else
    echo "$(date -Is) publish FAILED (need write deploy key or GITHUB_TOKEN)" >> /opt/kontent-zavod/logs/reports.log
    exit 0
  fi
)
