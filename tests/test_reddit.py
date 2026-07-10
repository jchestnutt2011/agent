import requests

from tools import reddit


def test_load_auth_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(reddit, "AUTH_FILE", tmp_path / "reddit_auth.json")
    assert reddit._load_auth() == {}


def test_load_auth_reads_user_and_feed(tmp_path, monkeypatch):
    auth_file = tmp_path / "reddit_auth.json"
    auth_file.write_text('{"user": "jnutt011", "feed": "abc123"}', encoding="utf-8")
    monkeypatch.setattr(reddit, "AUTH_FILE", auth_file)
    assert reddit._load_auth() == {"user": "jnutt011", "feed": "abc123"}


def test_load_auth_incomplete_data_returns_empty(tmp_path, monkeypatch):
    auth_file = tmp_path / "reddit_auth.json"
    auth_file.write_text('{"user": "jnutt011"}', encoding="utf-8")
    monkeypatch.setattr(reddit, "AUTH_FILE", auth_file)
    assert reddit._load_auth() == {}


def test_load_auth_malformed_json_returns_empty(tmp_path, monkeypatch):
    auth_file = tmp_path / "reddit_auth.json"
    auth_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(reddit, "AUTH_FILE", auth_file)
    assert reddit._load_auth() == {}


def test_fetch_posts_includes_auth_params_in_request(tmp_path, monkeypatch):
    auth_file = tmp_path / "reddit_auth.json"
    auth_file.write_text('{"user": "jnutt011", "feed": "abc123"}', encoding="utf-8")
    monkeypatch.setattr(reddit, "AUTH_FILE", auth_file)

    captured = {}

    class _FakeResponse:
        status_code = 200
        content = b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _FakeResponse()

    monkeypatch.setattr(reddit.requests, "get", fake_get)
    reddit.fetch_posts("gaming", limit=3)

    assert captured["params"]["user"] == "jnutt011"
    assert captured["params"]["feed"] == "abc123"


def test_fetch_posts_returns_error_string_on_network_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(reddit, "AUTH_FILE", tmp_path / "reddit_auth.json")

    def raise_error(*a, **k):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(reddit.requests, "get", raise_error)
    result = reddit.fetch_posts("gaming")
    assert isinstance(result, str)
    assert "Could not fetch r/gaming" in result


def test_fetch_posts_returns_error_string_on_malformed_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(reddit, "AUTH_FILE", tmp_path / "reddit_auth.json")

    class _FakeResponse:
        status_code = 200
        content = b"not valid xml <<<"

    monkeypatch.setattr(reddit.requests, "get", lambda *a, **k: _FakeResponse())
    result = reddit.fetch_posts("gaming")
    assert isinstance(result, str)
    assert "Could not parse r/gaming feed" in result


def test_fetch_posts_does_not_sleep_after_final_429(tmp_path, monkeypatch):
    """A persistent 429 should give up without a wasted trailing sleep."""
    monkeypatch.setattr(reddit, "AUTH_FILE", tmp_path / "reddit_auth.json")

    class _FakeResponse:
        status_code = 429
        content = b""

    sleeps = []
    monkeypatch.setattr(reddit.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(reddit.requests, "get", lambda *a, **k: _FakeResponse())

    result = reddit.fetch_posts("gaming")

    assert "HTTP 429" in result
    # 3 attempts, but only 2 sleeps (none after the last attempt).
    assert sleeps == [15, 30]
