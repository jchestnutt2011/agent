from tools import telegram_notify


def test_send_message_noop_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(telegram_notify, "AUTH_FILE", tmp_path / "telegram_auth.json")
    assert telegram_notify.send_message("hello") is False


def test_send_message_noop_when_incomplete_config(tmp_path, monkeypatch):
    auth_file = tmp_path / "telegram_auth.json"
    auth_file.write_text('{"bot_token": "123:abc"}', encoding="utf-8")
    monkeypatch.setattr(telegram_notify, "AUTH_FILE", auth_file)
    assert telegram_notify.send_message("hello") is False


def test_send_message_posts_to_correct_url_when_configured(tmp_path, monkeypatch):
    auth_file = tmp_path / "telegram_auth.json"
    auth_file.write_text('{"bot_token": "123:abc", "chat_id": "999"}', encoding="utf-8")
    monkeypatch.setattr(telegram_notify, "AUTH_FILE", auth_file)

    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(telegram_notify.requests, "post", fake_post)
    result = telegram_notify.send_message("hello")

    assert result is True
    assert captured["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert captured["json"]["chat_id"] == "999"
    assert captured["json"]["text"] == "hello"


def test_send_message_returns_false_on_request_failure(tmp_path, monkeypatch):
    import requests

    auth_file = tmp_path / "telegram_auth.json"
    auth_file.write_text('{"bot_token": "123:abc", "chat_id": "999"}', encoding="utf-8")
    monkeypatch.setattr(telegram_notify, "AUTH_FILE", auth_file)

    def raise_error(*a, **k):
        raise requests.RequestException("network down")

    monkeypatch.setattr(telegram_notify.requests, "post", raise_error)
    assert telegram_notify.send_message("hello") is False
