import json
from datetime import datetime, timedelta

import job_watchdog as watchdog


def _job(name="Test Job", log_file="test.log", max_staleness_minutes=45):
    return {"name": name, "log_file": log_file, "max_staleness_minutes": max_staleness_minutes}


def _write_log(tmp_path, name, content, mtime=None):
    path = tmp_path / name
    path.write_bytes(content.encode("utf-8"))
    if mtime is not None:
        ts = mtime.timestamp()
        import os
        os.utime(path, (ts, ts))
    return path


def test_check_job_missing_log_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    status, detail = watchdog._check_job(_job(log_file="missing.log"), datetime.now())
    assert status == "stale"
    assert "does not exist" in detail


def test_check_job_fresh_clean_log_is_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    _write_log(tmp_path, "test.log", "No new alerts to evaluate.\n", mtime=datetime.now())
    status, detail = watchdog._check_job(_job(), datetime.now())
    assert status == "ok"


def test_check_job_stale_log_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    old = datetime.now() - timedelta(minutes=90)
    _write_log(tmp_path, "test.log", "No new alerts to evaluate.\n", mtime=old)
    status, detail = watchdog._check_job(_job(max_staleness_minutes=45), datetime.now())
    assert status == "stale"
    assert "90 min ago" in detail


def test_check_job_traceback_in_recent_log_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    content = "Running job...\nTraceback (most recent call last):\nValueError: boom\n"
    _write_log(tmp_path, "test.log", content, mtime=datetime.now())
    status, detail = watchdog._check_job(_job(), datetime.now())
    assert status == "error"
    assert "Traceback" in detail


def test_check_job_traceback_outside_tail_window_is_ignored(tmp_path, monkeypatch):
    """A crash that scrolled out of the tail window (many successful runs
    since) shouldn't keep flagging as an active error forever."""
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    monkeypatch.setattr(watchdog, "TAIL_BYTES", 50)
    old_crash = "Traceback (most recent call last):\nValueError: boom\n"
    padding = "ok\n" * 100
    _write_log(tmp_path, "test.log", old_crash + padding, mtime=datetime.now())
    status, detail = watchdog._check_job(_job(), datetime.now())
    assert status == "ok"


def test_check_does_not_notify_on_first_seen_healthy_job(tmp_path, monkeypatch):
    """A job checked for the very first time and found healthy is just a
    baseline — nothing wrong happened, so it shouldn't page."""
    monkeypatch.setattr(watchdog, "CONFIG_FILE", tmp_path / "job_watchdog_config.json")
    monkeypatch.setattr(watchdog, "STATE_FILE", tmp_path / "job_watchdog_state.json")
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    (tmp_path / "job_watchdog_config.json").write_text(
        json.dumps({"jobs": [_job(log_file="test.log")]}), encoding="utf-8"
    )
    _write_log(tmp_path, "test.log", "ok\n", mtime=datetime.now())

    sent_messages = []
    monkeypatch.setattr(watchdog.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watchdog.check()

    assert sent_messages == []
    assert "baseline" in results[0]
    state = watchdog._load_state()
    assert state["Test Job"]["status"] == "ok"


def test_check_notifies_on_first_seen_broken_job(tmp_path, monkeypatch):
    """Unlike the healthy baseline case, a job that's already broken the
    very first time it's checked is still worth an immediate page."""
    monkeypatch.setattr(watchdog, "CONFIG_FILE", tmp_path / "job_watchdog_config.json")
    monkeypatch.setattr(watchdog, "STATE_FILE", tmp_path / "job_watchdog_state.json")
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    (tmp_path / "job_watchdog_config.json").write_text(
        json.dumps({"jobs": [_job(log_file="missing.log")]}), encoding="utf-8"
    )

    sent_messages = []
    monkeypatch.setattr(watchdog.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watchdog.check()

    assert len(sent_messages) == 1
    state = watchdog._load_state()
    assert state["Test Job"]["status"] == "stale"


def test_check_does_not_renotify_when_status_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "CONFIG_FILE", tmp_path / "job_watchdog_config.json")
    monkeypatch.setattr(watchdog, "STATE_FILE", tmp_path / "job_watchdog_state.json")
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    (tmp_path / "job_watchdog_config.json").write_text(
        json.dumps({"jobs": [_job(log_file="test.log")]}), encoding="utf-8"
    )
    _write_log(tmp_path, "test.log", "ok\n", mtime=datetime.now())
    watchdog._save_state({"Test Job": {"status": "ok", "detail": "x", "checked_at": "x"}})

    sent_messages = []
    monkeypatch.setattr(watchdog.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watchdog.check()

    assert sent_messages == []
    assert "no change" in results[0]


def test_check_notifies_recovery_after_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "CONFIG_FILE", tmp_path / "job_watchdog_config.json")
    monkeypatch.setattr(watchdog, "STATE_FILE", tmp_path / "job_watchdog_state.json")
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    (tmp_path / "job_watchdog_config.json").write_text(
        json.dumps({"jobs": [_job(log_file="test.log")]}), encoding="utf-8"
    )
    _write_log(tmp_path, "test.log", "ok\n", mtime=datetime.now())
    watchdog._save_state({"Test Job": {"status": "stale", "detail": "x", "checked_at": "x"}})

    sent_messages = []
    monkeypatch.setattr(watchdog.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watchdog.check()

    assert len(sent_messages) == 1
    assert "recovered" in sent_messages[0]
    assert watchdog._load_state()["Test Job"]["status"] == "ok"


def test_check_does_not_persist_transition_when_telegram_send_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "CONFIG_FILE", tmp_path / "job_watchdog_config.json")
    monkeypatch.setattr(watchdog, "STATE_FILE", tmp_path / "job_watchdog_state.json")
    monkeypatch.setattr(watchdog, "BASE_DIR", tmp_path)
    (tmp_path / "job_watchdog_config.json").write_text(
        json.dumps({"jobs": [_job(log_file="missing.log")]}), encoding="utf-8"
    )
    monkeypatch.setattr(watchdog.telegram_notify, "send_message", lambda text: False)

    watchdog.check()

    assert watchdog._load_state() == {}  # not persisted — must retry notifying next cycle
