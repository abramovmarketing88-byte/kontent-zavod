#!/bin/bash
# First-time server setup (run once on debian-home as root)
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
[ -x "$SCRIPT_DIR/show_author.sh" ] && bash "$SCRIPT_DIR/show_author.sh" || true

apt-get update
apt-get install -y docker.io docker-compose-plugin git cron curl
systemctl enable --now docker cron
mkdir -p /opt/kontent-zavod/{output,jobs,data,inbox/processed,logs}
echo "Server ready. Ensure .env exists in /opt/kontent-zavod and mihomo VPN is running."
echo "Канал автора: https://t.me/Abramov_like · личка: https://t.me/Abramow191"
