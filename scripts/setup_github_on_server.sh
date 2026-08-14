#!/bin/bash
# One-time: connect /opt/kontent-zavod to GitHub and enable auto-update cron
set -eu
REPO="${1:-abramovmarketing88-byte/kontent-zavod}"
cd /opt/kontent-zavod

if [ ! -f /root/.ssh/github_deploy ]; then
  ssh-keygen -t ed25519 -f /root/.ssh/github_deploy -N "" -C "kontent-zavod-deploy"
fi

if ! grep -q github_deploy /root/.ssh/config 2>/dev/null; then
  cat >> /root/.ssh/config <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile /root/.ssh/github_deploy
  StrictHostKeyChecking accept-new
EOF
  chmod 600 /root/.ssh/config
fi

if [ ! -d .git ]; then
  git init
  git config user.email "deploy@kontent-zavod.local"
  git config user.name "kontent-zavod-deploy"
fi

git remote remove origin 2>/dev/null || true
git remote add origin "git@github.com:${REPO}.git"

echo "=== Add this deploy key to GitHub repo (Settings → Deploy keys, read-only) ==="
cat /root/.ssh/github_deploy.pub
echo "=== Then run: git fetch origin main && git reset --hard origin/main && bash scripts/install_cron.sh ==="
