"""Runs on a schedule (every 15 min via Windows Task Scheduler, like the jobs
it watches). Checks that each configured scheduled job (weather_alert_monitor,
daily_briefing) is actually running and not silently broken.

Two independent signals, both derived from the job's own log file rather than
Windows Task Scheduler's LastRunTime/LastTaskResult — that keeps this
decoupled from the scheduling mechanism (works the same if a job later moves
to cron/systemd) and, more importantly, catches the exact class of bug this
project already hit once: a job that runs on schedule, exits 0, and appends a
log line every cycle while quietly doing the wrong thing internally would
look "healthy" to Task Scheduler but not to a human reading the log.

1. Staleness — the log file's mtime hasn't moved in longer than the job's
   expected interval. Catches Task Scheduler misfiring, a broken venv, the
   PC being off, etc.
2. Crash — a Traceback appears in the last chunk of the log. Catches a job
   that's still firing on schedule but has been dying immediately every run
   (e.g. an import error from a bad edit) — staleness alone would miss this
   entirely since the log keeps getting touched.

Notification is edge-triggered on status change (ok -> stale/error, or
stale/error -> ok), persisted in job_watchdog_state.json, for the same reason
weather_alert_monitor.py dedupes by content: a job that's been down for six
hours shouldn't re-page every 15 minutes, but its recovery is worth knowing
about too.
"""

import json
from datetime import datetime
from pathlib import Path

import state_store
from tools import telegram_notify

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "job_watchdog_config.json"
STATE_FILE = BASE_DIR / "job_watchdog_state.json"

# How far from the end of the log to look for a crash. Generous enough to
# cover a multi-line Python traceback without reading a potentially large
# log file in full.
TAIL_BYTES = 4000


def _load_config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _load_state():
    return state_store.load_json_state(STATE_FILE)


def _save_state(state):
    state_store.save_json_state(STATE_FILE, state)


def _tail_has_traceback(log_path):
    """Bytes-level check, not text decode — the log is written by whatever
    codepage the scheduled task's console uses, which has already produced
    mojibake for non-ASCII characters in this project. "Traceback" itself is
    always plain ASCII, so searching raw bytes sidesteps encoding entirely."""
    size = log_path.stat().st_size
    with open(log_path, "rb") as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
        tail = f.read()
    return b"Traceback" in tail


def _check_job(job, now):
    """Returns (status, detail) where status is one of 'ok', 'stale', 'error'."""
    log_path = BASE_DIR / job["log_file"]

    if not log_path.exists():
        return "stale", f"log file {job['log_file']} does not exist"

    mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
    age_minutes = (now - mtime).total_seconds() / 60
    if age_minutes > job["max_staleness_minutes"]:
        return "stale", f"last log activity {age_minutes:.0f} min ago (expected within {job['max_staleness_minutes']})"

    if _tail_has_traceback(log_path):
        return "error", f"a Traceback appears in the last {TAIL_BYTES} bytes of {job['log_file']}"

    return "ok", f"log updated {age_minutes:.0f} min ago"


def _build_message(job_name, old_status, new_status, detail):
    if new_status == "ok":
        return f"✅ <b>{job_name}</b> recovered — running normally again ({detail})."
    icon = "\U0001F525" if new_status == "error" else "⚠️"
    label = "crashing" if new_status == "error" else "not running"
    return f"{icon} <b>{job_name}</b> appears to be {label}: {detail}."


def check():
    """Runs one monitoring pass. Returns a list of human-readable result lines."""
    config = _load_config()
    state = _load_state()
    now = datetime.now()
    results = []

    for job in config.get("jobs", []):
        status, detail = _check_job(job, now)
        previous = state.get(job["name"], {}).get("status")

        if previous is None and status == "ok":
            # First time this job has ever been checked and it's healthy —
            # nothing wrong to report, just establishing a baseline.
            results.append(f"{job['name']}: baseline ok ({detail}) — not notified (first check)")
        elif status != previous:
            message = _build_message(job["name"], previous, status, detail)
            sent = telegram_notify.send_message(message)
            results.append(f"{job['name']}: {previous or 'unknown'} -> {status} ({detail}) — notified: {sent}")
            if not sent:
                # Don't persist the transition — retry notifying next cycle
                # instead of silently accepting the new status unannounced.
                continue

        else:
            results.append(f"{job['name']}: {status} ({detail}) — no change, not notified")

        state[job["name"]] = {"status": status, "detail": detail, "checked_at": now.isoformat()}

    _save_state(state)
    return results


def main():
    for line in check():
        print(line)


if __name__ == "__main__":
    main()
