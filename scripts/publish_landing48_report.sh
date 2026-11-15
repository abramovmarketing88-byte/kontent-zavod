#!/bin/bash
# Push landing-48 URL into branch run-reports for Cloud Agents to read.
set -euo pipefail
cd /opt/kontent-zavod
mkdir -p reports logs

if [ ! -f reports/landing-48.url ]; then
  echo "no reports/landing-48.url — skip"
  exit 0
fi

REPORTS_GIT_PUSH=true
GITHUB_TOKEN=""
if [ -f .env ]; then
  REPORTS_GIT_PUSH=$(grep -E '^REPORTS_GIT_PUSH=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
  REPORTS_GIT_PUSH=${REPORTS_GIT_PUSH:-true}
  GITHUB_TOKEN=$(grep -E '^GITHUB_TOKEN=' .env | tail -1 | cut -d= -f2- | tr -d '\r' || true)
fi

if [ "${REPORTS_GIT_PUSH}" = "false" ]; then
  exit 0
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

URL=$(git -C /opt/kontent-zavod remote get-url origin)
if [ -n "${GITHUB_TOKEN}" ]; then
  URL="https://x-access-token:${GITHUB_TOKEN}@github.com/abramovmarketing88-byte/kontent-zavod.git"
fi

(
  cd "$WORK"
  git init -q
  git remote add origin "$URL"
  if git fetch -q origin run-reports 2>/dev/null; then
    git checkout -q -b run-reports origin/run-reports
  else
    git checkout -q -b run-reports
  fi
  mkdir -p reports
  cp /opt/kontent-zavod/reports/landing-48.url reports/
  cp /opt/kontent-zavod/reports/landing-48.txt reports/ 2>/dev/null || true
  git add reports/landing-48.url
  [ -f reports/landing-48.txt ] && git add reports/landing-48.txt || true
  if git diff --cached --quiet; then
    exit 0
  fi
  git -c user.name="kontent-zavod" -c user.email="reports@kontent-zavod.local" \
    commit -qm "landing48: $(tr -d '\n' < reports/landing-48.url)"
  if git push origin run-reports; then
    echo "$(date -Is) published landing-48.url" >> /opt/kontent-zavod/logs/reports.log
  else
    echo "$(date -Is) landing48 report push FAILED" >> /opt/kontent-zavod/logs/reports.log
  fi
)
