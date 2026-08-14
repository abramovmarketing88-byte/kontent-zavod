"""Print your Telegram chat_id for TELEGRAM_OWNER_CHAT_ID.

Usage:
  1. Open @The2TestGPTBot in Telegram and send /start
  2. Run: python scripts/telegram_chat_id.py
"""
from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in .env (same bot as MCP server)", file=sys.stderr)
        sys.exit(1)

    resp = httpx.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        timeout=60.0,
    )
    data = resp.json()
    if not data.get("ok"):
        print("API error:", data, file=sys.stderr)
        sys.exit(1)

    seen: dict[int, str] = {}
    for update in data.get("result", []):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        chat = msg["chat"]
        if chat.get("type") != "private":
            continue
        user = chat.get("first_name", "")
        username = chat.get("username", "")
        label = f"@{username}" if username else user
        seen[chat["id"]] = label

    if not seen:
        print("No private chats found. Send /start to your bot first.", file=sys.stderr)
        sys.exit(1)

    print("Add to .env:\n")
    for chat_id, label in seen.items():
        print(f"TELEGRAM_OWNER_CHAT_ID={chat_id}  # {label}")


if __name__ == "__main__":
    main()
