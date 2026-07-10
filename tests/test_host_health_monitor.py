import json

import requests

import host_health_monitor as monitor


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_check_disk_ok_when_above_threshold(monkeypatch):
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda path: (100 * 1024**3, 50 * 1024**3, 50 * 1024**3))
    status, detail = monitor._check_disk({"disk_path": "C:\\", "min_free_gb": 10})
    assert status == "ok"
    assert "50.0 GB free" in detail


def test_check_disk_unhealthy_when_below_threshold(monkeypatch):
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda path: (100 * 1024**3, 95 * 1024**3, 5 * 1024**3))
    status, detail = monitor._check_disk({"disk_path": "C:\\", "min_free_gb": 10})
    assert status == "unhealthy"
    assert "5.0 GB free" in detail


def test_check_disk_handles_os_error(monkeypatch):
    def raise_error(path):
        raise OSError("no such disk")
    monkeypatch.setattr(monitor.shutil, "disk_usage", raise_error)
    status, detail = monitor._check_disk({"disk_path": "Z:\\"})
    assert status == "unhealthy"
    assert "could not read disk usage" in detail


def test_check_http_ok_on_200(monkeypatch):
    monkeypatch.setattr(monitor.requests, "get", lambda url, timeout: _FakeResponse(200))
    status, detail = monitor._check_http("Ollama", "http://localhost:11434/api/version")
    assert status == "ok"


def test_check_http_unhealthy_on_connection_error(monkeypatch):
    def raise_error(url, timeout):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(monitor.requests, "get", raise_error)
    status, detail = monitor._check_http("Ollama", "http://localhost:11434/api/version")
    assert status == "unhealthy"
    assert "unreachable" in detail


def test_check_does_not_notify_on_first_seen_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "host_health_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "host_health_state.json")
    (tmp_path / "host_health_config.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda path: (100 * 1024**3, 50 * 1024**3, 50 * 1024**3))
    monkeypatch.setattr(monitor.requests, "get", lambda url, timeout: _FakeResponse(200))

    sent_messages = []
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = monitor.check()

    assert sent_messages == []
    assert all("baseline" in line for line in results)
    state = monitor._load_state()
    assert state["Disk Space"]["status"] == "ok"
    assert state["Ollama"]["status"] == "ok"
    assert state["Streamlit"]["status"] == "ok"


def test_check_notifies_on_first_seen_unhealthy(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "host_health_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "host_health_state.json")
    (tmp_path / "host_health_config.json").write_text(json.dumps({"min_free_gb": 10}), encoding="utf-8")
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda path: (100 * 1024**3, 99 * 1024**3, 1 * 1024**3))
    monkeypatch.setattr(monitor.requests, "get", lambda url, timeout: _FakeResponse(200))

    sent_messages = []
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    monitor.check()

    assert len(sent_messages) == 1
    assert "Disk Space" in sent_messages[0]
    state = monitor._load_state()
    assert state["Disk Space"]["status"] == "unhealthy"


def test_check_notifies_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "host_health_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "host_health_state.json")
    (tmp_path / "host_health_config.json").write_text(json.dumps({}), encoding="utf-8")
    monitor._save_state({
        "Disk Space": {"status": "unhealthy", "detail": "x", "checked_at": "x"},
        "Ollama": {"status": "ok", "detail": "x", "checked_at": "x"},
        "Streamlit": {"status": "ok", "detail": "x", "checked_at": "x"},
    })
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda path: (100 * 1024**3, 50 * 1024**3, 50 * 1024**3))
    monkeypatch.setattr(monitor.requests, "get", lambda url, timeout: _FakeResponse(200))

    sent_messages = []
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    monitor.check()

    assert len(sent_messages) == 1
    assert "recovered" in sent_messages[0]
    assert monitor._load_state()["Disk Space"]["status"] == "ok"


def test_check_does_not_renotify_when_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "host_health_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "host_health_state.json")
    (tmp_path / "host_health_config.json").write_text(json.dumps({}), encoding="utf-8")
    monitor._save_state({
        "Disk Space": {"status": "ok", "detail": "x", "checked_at": "x"},
        "Ollama": {"status": "ok", "detail": "x", "checked_at": "x"},
        "Streamlit": {"status": "ok", "detail": "x", "checked_at": "x"},
    })
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda path: (100 * 1024**3, 50 * 1024**3, 50 * 1024**3))
    monkeypatch.setattr(monitor.requests, "get", lambda url, timeout: _FakeResponse(200))

    sent_messages = []
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = monitor.check()

    assert sent_messages == []
    assert all("no change" in line for line in results)


def test_check_does_not_persist_when_telegram_send_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "host_health_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "host_health_state.json")
    (tmp_path / "host_health_config.json").write_text(json.dumps({"min_free_gb": 10}), encoding="utf-8")
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda path: (100 * 1024**3, 99 * 1024**3, 1 * 1024**3))
    monkeypatch.setattr(monitor.requests, "get", lambda url, timeout: _FakeResponse(200))
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: False)

    monitor.check()

    # Disk Space's transition wasn't persisted (retry next cycle), but the
    # other checks' first-seen-healthy baselines still are — independent checks.
    assert "Disk Space" not in monitor._load_state()
