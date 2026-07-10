"""Shared JSON state-file helpers used by every scheduled monitor in this
project (weather_alert_monitor, job_watchdog, page_watcher,
host_health_monitor). Each monitor still owns its own STATE_FILE path and a
thin _load_state()/_save_state() wrapper around these — this only removes
the identical load/save boilerplate that was copy-pasted into all four.
"""

import json


def load_json_state(path):
    """Returns {} if the file doesn't exist or contains invalid JSON —
    never raises, so a corrupted state file degrades to "start fresh"
    rather than crashing the monitor."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_json_state(path, data):
    """Atomic write via a temp file + rename, so a crash mid-write can't
    leave a corrupted/truncated state file behind."""
    tmp_file = path.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_file.replace(path)
