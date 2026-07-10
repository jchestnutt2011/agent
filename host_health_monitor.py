"""Runs on a schedule (every 15 min via Windows Task Scheduler, alongside the
other monitors in this project). Checks the health of the headless PC this
agent itself runs on: disk space, and whether Ollama and Streamlit are
actually reachable.

Motivation: every other monitor in this project (weather_alert_monitor,
daily_briefing, page_watcher) depends on this one PC staying up, Ollama
staying reachable, and disk not filling up from logs/state files — but none
of them would notice if the PC itself were the problem. If Ollama crashes,
disk fills up, or Streamlit dies, nothing else here can page out about it.

Same edge-triggered notify shape as job_watchdog.py: only ping on a status
transition (ok -> unhealthy or unhealthy -> ok), not on every cycle, so a
persistent problem doesn't spam every 15 minutes — but recovery is reported
too, so "did it fix itself" isn't left ambiguous.

Known limitation: _check_http only confirms Ollama/Streamlit answered an
HTTP request, not that they're actually working correctly (e.g. Ollama
responding 200 while the model itself is wedged or OOMing wouldn't be
caught). A real inference call would catch more but costs real GPU time
and latency every 15 minutes for a check that's mostly meant to catch
"the process died" or "the PC is off" — a much cheaper and more common
failure than "the service is up but broken." Acceptable for v1; revisit
if a wedged-but-responsive failure actually happens in practice.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import requests

import state_store
from tools import telegram_notify

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "host_health_config.json"
STATE_FILE = BASE_DIR / "host_health_state.json"

DEFAULT_DISK_PATH = "C:\\"
DEFAULT_MIN_FREE_GB = 10
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/version"
DEFAULT_STREAMLIT_URL = "http://localhost:8501"

HTTP_TIMEOUT = 5


def _load_config():
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _load_state():
    return state_store.load_json_state(STATE_FILE)


def _save_state(state):
    state_store.save_json_state(STATE_FILE, state)


def _check_disk(config):
    path = config.get("disk_path", DEFAULT_DISK_PATH)
    min_free_gb = config.get("min_free_gb", DEFAULT_MIN_FREE_GB)
    try:
        _, _, free = shutil.disk_usage(path)
    except OSError as e:
        return "unhealthy", f"could not read disk usage for {path}: {e}"

    free_gb = free / (1024 ** 3)
    if free_gb < min_free_gb:
        return "unhealthy", f"only {free_gb:.1f} GB free on {path} (minimum {min_free_gb} GB)"
    return "ok", f"{free_gb:.1f} GB free on {path}"


def _check_http(name, url):
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        return "unhealthy", f"{name} unreachable at {url}: {e}"
    return "ok", f"{name} responded {resp.status_code} at {url}"


def _build_message(check_name, new_status, detail):
    if new_status == "ok":
        return f"✅ <b>{check_name}</b> recovered — {detail}."
    return f"\U0001F525 <b>{check_name}</b> is unhealthy: {detail}."


def check():
    """Runs one monitoring pass. Returns a list of human-readable result lines."""
    config = _load_config()
    state = _load_state()
    now = datetime.now().isoformat()
    results = []

    checks = [
        ("Disk Space", lambda: _check_disk(config)),
        ("Ollama", lambda: _check_http("Ollama", config.get("ollama_url", DEFAULT_OLLAMA_URL))),
        ("Streamlit", lambda: _check_http("Streamlit", config.get("streamlit_url", DEFAULT_STREAMLIT_URL))),
    ]

    for name, fn in checks:
        status, detail = fn()
        previous = state.get(name, {}).get("status")

        if previous is None and status == "ok":
            # First time this check has ever run and it's healthy — nothing
            # wrong to report, just establishing a baseline.
            results.append(f"{name}: baseline ok ({detail}) — not notified (first check)")
        elif status != previous:
            message = _build_message(name, status, detail)
            sent = telegram_notify.send_message(message)
            results.append(f"{name}: {previous or 'unknown'} -> {status} ({detail}) — notified: {sent}")
            if not sent:
                # Don't persist the transition — retry notifying next cycle
                # instead of silently accepting the new status unannounced.
                continue
        else:
            results.append(f"{name}: {status} ({detail}) — no change, not notified")

        state[name] = {"status": status, "detail": detail, "checked_at": now}

    _save_state(state)
    return results


def main():
    for line in check():
        print(line)


if __name__ == "__main__":
    main()
