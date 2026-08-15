#!/bin/bash
# Container entrypoint: drop dead proxy, then exec the worker command.
set -euo pipefail

PROXY_URL="${HTTP_PROXY:-${HTTPS_PROXY:-http://127.0.0.1:7890}}"
PROXY_REQUIRED="${PROXY_REQUIRED:-false}"

proxy_ok() {
  local host port
  host=$(printf '%s' "$PROXY_URL" | sed -E 's#^[a-zA-Z0-9]+://([^:/]+).*#\1#')
  port=$(printf '%s' "$PROXY_URL" | sed -E 's#^[a-zA-Z0-9]+://[^:/]+:([0-9]+).*#\1#')
  host=${host:-127.0.0.1}
  port=${port:-7890}
  # TCP check without requiring curl in PATH for the probe itself
  if command -v curl >/dev/null 2>&1; then
    curl -sS -o /dev/null --connect-timeout 2 --max-time 4 -x "$PROXY_URL" https://api.telegram.org \
      && return 0
    return 1
  fi
  # Fallback: bash /dev/tcp
  timeout 2 bash -c "echo >/dev/tcp/${host}/${port}" 2>/dev/null
}

if [ -n "${HTTP_PROXY:-}${HTTPS_PROXY:-}" ]; then
  if proxy_ok; then
    echo "[entrypoint] proxy OK: $PROXY_URL"
  else
    if [ "${PROXY_REQUIRED}" = "true" ] || [ "${PROXY_REQUIRED}" = "1" ]; then
      echo "[entrypoint] ERROR: proxy required but dead: $PROXY_URL" >&2
      exit 1
    fi
    echo "[entrypoint] proxy dead — clearing HTTP(S)_PROXY ($PROXY_URL)"
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
    export HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""
  fi
fi

exec "$@"
