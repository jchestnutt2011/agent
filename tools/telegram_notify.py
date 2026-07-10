import json
from pathlib import Path

import requests

# Optional, gitignored: {"bot_token": "...", "chat_id": "..."}. Absent by
# default, in which case send_message() is a silent no-op — daily_briefing.py
# and the Streamlit dashboard work exactly as before without this file.
AUTH_FILE = Path(__file__).parent.parent / "telegram_auth.json"


def _load_auth():
    if not AUTH_FILE.exists():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not data.get("bot_token") or not data.get("chat_id"):
        return None
    return data


def send_message(text):
    """Send a Markdown-formatted message via the Telegram Bot API. Returns
    True on success, False if not configured or the request failed — never
    raises, since a failed notification shouldn't break briefing generation."""
    auth = _load_auth()
    if not auth:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{auth['bot_token']}/sendMessage",
            json={"chat_id": auth["chat_id"], "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException:
        return False
