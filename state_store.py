"""Shared JSON state-file helpers used by every scheduled monitor in this
project (weather_alert_monitor, job_watchdog, page_watcher,
host_health_monitor). Each monitor still owns its own STATE_FILE path and a
thin _load_state()/_save_state() wrapper around these — this only removes
the identical load/save boilerplate that was copy-pasted into all four.

file_lock/merge_json_state address a real race: page_watch_config.json and
page_watch_state.json are written by both the scheduled page_watcher.py run
and the Streamlit price-watch UI. A naive load-mutate-save from a snapshot
taken minutes earlier (page_watcher.py's check() loop can take a while,
fetching several real web pages) can clobber a concurrent edit from the
other side. Scope is deliberately narrow: only the merge's own read+write
is lock-protected, not the slow network fetches that produce the values
being merged.
"""

import contextlib
import json
import os
import time

# A lock older than this is assumed to be abandoned by a crashed process,
# not held by a live one — the critical sections this guards are a single
# JSON read+write (milliseconds), never a network fetch, so anything still
# "held" this long didn't release cleanly and would otherwise wedge every
# future writer forever.
STALE_LOCK_SECONDS = 30


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


@contextlib.contextmanager
def file_lock(path, timeout=5, poll_interval=0.05):
    """Best-effort cross-process mutual exclusion via atomic lock-file
    creation (os.O_CREAT | os.O_EXCL) — portable, no platform-specific
    locking APIs needed. Raises TimeoutError if the lock can't be acquired
    within `timeout` seconds, rather than hanging forever."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > STALE_LOCK_SECONDS:
                    lock_path.unlink()
                    continue  # retry immediately, no need to wait out the poll interval
            except FileNotFoundError:
                continue  # lock was released between our open() and stat() — retry now
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire lock on {lock_path} within {timeout}s")
            time.sleep(poll_interval)

    try:
        os.close(fd)
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def merge_json_state(path, updates, timeout=5):
    """Read-modify-write under a short-held lock, merging only `updates`
    onto whatever's currently on disk — not the caller's possibly-stale
    full snapshot. Use this instead of save_json_state() wherever another
    process might also be writing the same file concurrently."""
    if not updates:
        return
    with file_lock(path, timeout=timeout):
        current = load_json_state(path)
        current.update(updates)
        save_json_state(path, current)
