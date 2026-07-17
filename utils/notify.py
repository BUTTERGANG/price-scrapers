"""Best-effort Telegram notifications for price alerts and scraper failures.

Destination chat IDs come from, in order:
  1. TELEGRAM_CHAT_ID env var — comma-separated for multiple chats.
  2. config/notify.json — chat IDs auto-registered when someone sends the
     bot /start (see telegram_bot.py::cmd_start → register_chat).

Sending uses the plain Telegram HTTP API via requests (no dependency on the
bot's async framework) so it's safe to call from runner threads. notify()
never raises: with no token or no chat IDs it's a silent no-op, and network
errors are logged and swallowed — a notification failure must never fail a
scrape run.
"""
import json
import logging
import os
import threading
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

NOTIFY_PATH = Path("config/notify.json")

_file_lock = threading.Lock()


def _registered_chat_ids() -> list[str]:
    try:
        data = json.loads(NOTIFY_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [str(c) for c in data.get("chat_ids", [])]


def chat_ids() -> list[str]:
    """All destination chat IDs (env var first, then registered), deduplicated."""
    env = os.environ.get("TELEGRAM_CHAT_ID", "")
    ids = [c.strip() for c in env.split(",") if c.strip()]
    ids.extend(_registered_chat_ids())
    return list(dict.fromkeys(ids))


def register_chat(chat_id) -> bool:
    """Persist a chat ID to config/notify.json. Returns True if newly added."""
    chat_id = str(chat_id)
    with _file_lock:
        current = _registered_chat_ids()
        if chat_id in current:
            return False
        current.append(chat_id)
        NOTIFY_PATH.write_text(json.dumps({"chat_ids": current}, indent=2) + "\n")
    logger.info(f"Registered Telegram chat {chat_id} for notifications.")
    return True


def notify(text: str) -> int:
    """Send `text` to every configured chat. Returns how many sends succeeded."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return 0
    targets = chat_ids()
    if not targets:
        logger.debug("Notification dropped — no TELEGRAM_CHAT_ID and no registered chats.")
        return 0
    sent = 0
    for chat_id in targets:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
            if resp.ok:
                sent += 1
            else:
                logger.warning(
                    f"Telegram notify to {chat_id} failed: {resp.status_code} {resp.text[:200]}"
                )
        except requests.RequestException as e:
            logger.warning(f"Telegram notify to {chat_id} failed: {e}")
    return sent
