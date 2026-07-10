import json

import requests

import page_watcher as watcher


class _FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _page(name="Test Page", url="https://example.com/item", css_selector=None):
    return {"name": name, "url": url, "css_selector": css_selector}


def test_extract_text_strips_scripts_and_styles():
    html_content = "<html><body><script>evil()</script><style>.x{}</style><p>Hello  world</p></body></html>"
    assert watcher._extract_text(html_content) == "Hello world"


def test_extract_text_with_selector():
    html_content = '<div id="price">$19.99</div><div id="ad">Buy now!</div>'
    assert watcher._extract_text(html_content, "#price") == "$19.99"


def test_extract_text_missing_selector_returns_none():
    html_content = "<div id='price'>$19.99</div>"
    assert watcher._extract_text(html_content, "#nope") is None


def test_check_captures_baseline_without_notifying(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $10</p>"))
    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert sent_messages == []
    assert "baseline" in results[0]
    state = watcher._load_state()
    assert "Test Page" in state


def test_check_skips_unchanged_page(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")
    watcher._save_state({"Test Page": {"content_hash": watcher._content_hash("Price: $10"), "content_snippet": "Price: $10"}})

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $10</p>"))
    decide_calls = []
    monkeypatch.setattr(watcher, "_ask_model_to_decide", lambda *a: decide_calls.append(a) or (True, "x"))

    results = watcher.check()

    assert decide_calls == []
    assert "unchanged" in results[0]


def test_check_notifies_on_meaningful_change(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")
    watcher._save_state({"Test Page": {"content_hash": watcher._content_hash("Price: $10"), "content_snippet": "Price: $10"}})

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $5</p>"))
    monkeypatch.setattr(watcher, "_ask_model_to_decide", lambda name, old, new: (True, "price dropped"))
    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert len(sent_messages) == 1
    assert "price dropped" in sent_messages[0]
    state = watcher._load_state()
    assert state["Test Page"]["content_hash"] == watcher._content_hash("Price: $5")


def test_check_skips_noise_change_without_notifying(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")
    watcher._save_state({"Test Page": {"content_hash": watcher._content_hash("Price: $10 (1204 views)"), "content_snippet": "Price: $10 (1204 views)"}})

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $10 (1205 views)</p>"))
    monkeypatch.setattr(watcher, "_ask_model_to_decide", lambda name, old, new: (False, "just a view counter"))
    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert sent_messages == []
    assert "skipped" in results[0]
    # state still advances to the latest content so future diffs aren't stale
    state = watcher._load_state()
    assert state["Test Page"]["content_hash"] == watcher._content_hash("Price: $10 (1205 views)")


def test_check_does_not_persist_when_telegram_send_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")
    watcher._save_state({"Test Page": {"content_hash": watcher._content_hash("Price: $10"), "content_snippet": "Price: $10"}})

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $5</p>"))
    monkeypatch.setattr(watcher, "_ask_model_to_decide", lambda name, old, new: (True, "price dropped"))
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: False)

    results = watcher.check()

    assert "will retry" in results[0]
    state = watcher._load_state()
    assert state["Test Page"]["content_hash"] == watcher._content_hash("Price: $10")  # unchanged, retry next cycle


def test_check_handles_fetch_failure_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")

    def raise_error(url, headers, timeout):
        raise requests.ConnectionError("host unreachable")
    monkeypatch.setattr(watcher.requests, "get", raise_error)

    results = watcher.check()

    assert "could not check" in results[0]
    assert watcher._load_state() == {}


def test_ask_model_to_decide_handles_malformed_json_safely(monkeypatch):
    monkeypatch.setattr(watcher.ollama, "chat", lambda model, messages, format: {
        "message": {"content": "not valid json"}
    })
    notify, reason = watcher._ask_model_to_decide("Test Page", "old", "new")
    assert notify is False
    assert "precaution" in reason


def test_no_pages_configured_returns_no_results(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": []}), encoding="utf-8")

    assert watcher.check() == []
