#!/bin/bash
# Install GitHub Actions self-hosted runner on debian-home (non-root user).
# Usage: RUNNER_TOKEN=... bash scripts/install_github_runner.sh
set -eu
TOKEN="${RUNNER_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  echo "Set RUNNER_TOKEN"
  exit 1
fi

export http_proxy="${http_proxy:-http://127.0.0.1:7890}"
export https_proxy="${https_proxy:-http://127.0.0.1:7890}"

id github-runner >/dev/null 2>&1 || useradd -m -s /bin/bash github-runner
usermod -aG docker github-runner 2>/dev/null || true

install -d -m 0755 /opt/actions-runner
chown github-runner:github-runner /opt/actions-runner
cd /opt/actions-runner

VER="${RUNNER_VERSION:-2.336.0}"
TGZ="actions-runner-linux-x64-${VER}.tar.gz"
if [ ! -f ./config.sh ]; then
  sudo -u github-runner curl -fsSL -o "$TGZ" "https://github.com/actions/runner/releases/download/v${VER}/${TGZ}"
  sudo -u github-runner tar xzf "$TGZ"
  rm -f "$TGZ"
fi

if [ ! -f .runner ]; then
  sudo -u github-runner ./config.sh --unattended \
    --url https://github.com/abramovmarketing88-byte/kontent-zavod \
    --token "$TOKEN" \
    --name debian-home \
    --labels debian-home \
    --work _work \
    --replace
fi

# systemd unit as github-runner
if [ ! -f /etc/systemd/system/actions.runner.kontent-zavod.debian-home.service ]; then
  sudo -u github-runner ./svc.sh install github-runner || true
fi
./svc.sh start || true
./svc.sh status || true
echo "GitHub runner installed on debian-home"
