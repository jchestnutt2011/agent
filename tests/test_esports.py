import json

import requests

from tools import esports


class _FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _raw_match(id=1, team1="Team A", team2="Team B", league="Test League", scheduled_at="2026-07-11T09:00:00Z"):
    return {
        "id": id,
        "opponents": [
            {"opponent": {"name": team1}},
            {"opponent": {"name": team2}},
        ],
        "scheduled_at": scheduled_at,
        "status": "not_started",
        "league": {"name": league},
        "serie": {"full_name": "2026"},
        "tournament": {"name": "Group A"},
        "number_of_games": 3,
        "streams_list": [
            {"official": False, "raw_url": "https://twitch.tv/unofficial"},
            {"official": True, "raw_url": "https://twitch.tv/official"},
        ],
    }


def test_load_api_key_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(esports, "AUTH_FILE", tmp_path / "pandascore_auth.json")
    assert esports._load_api_key() is None


def test_load_api_key_malformed_json_returns_none(tmp_path, monkeypatch):
    auth_file = tmp_path / "pandascore_auth.json"
    auth_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(esports, "AUTH_FILE", auth_file)
    assert esports._load_api_key() is None


def test_load_api_key_reads_key(tmp_path, monkeypatch):
    auth_file = tmp_path / "pandascore_auth.json"
    auth_file.write_text(json.dumps({"api_key": "abc123"}), encoding="utf-8")
    monkeypatch.setattr(esports, "AUTH_FILE", auth_file)
    assert esports._load_api_key() == "abc123"


def test_normalize_match_prefers_official_stream():
    normalized = esports._normalize_match(_raw_match(), "dota2")
    assert normalized["stream_url"] == "https://twitch.tv/official"


def test_normalize_match_extracts_teams_and_metadata():
    normalized = esports._normalize_match(_raw_match(team1="Alpha", team2="Beta"), "csgo")
    assert normalized["team1"] == "Alpha"
    assert normalized["team2"] == "Beta"
    assert normalized["game"] == "CS2"
    assert normalized["league"] == "Test League"
    assert normalized["best_of"] == 3


def test_normalize_match_handles_missing_opponents_gracefully():
    raw = {"id": 1, "opponents": [], "streams_list": []}
    normalized = esports._normalize_match(raw, "lol")
    assert normalized["team1"] == "TBD"
    assert normalized["team2"] == "TBD"
    assert normalized["stream_url"] is None


def test_get_matches_unknown_game_returns_error():
    result = esports.get_matches("overwatch")
    assert result["matches"] == []
    assert "Unknown game" in result["error"]


def test_get_matches_no_api_key_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(esports, "AUTH_FILE", tmp_path / "pandascore_auth.json")
    result = esports.get_matches("dota2")
    assert result["matches"] == []
    assert "not configured" in result["error"]


def test_get_matches_success(monkeypatch):
    monkeypatch.setattr(esports, "_load_api_key", lambda: "fake-key")
    monkeypatch.setattr(
        esports.requests, "get",
        lambda url, headers, params, timeout: _FakeResponse([_raw_match()], 200),
    )
    result = esports.get_matches("dota2", limit=5)
    assert result["error"] is None
    assert len(result["matches"]) == 1
    assert result["matches"][0]["team1"] == "Team A"


def test_get_matches_handles_401(monkeypatch):
    monkeypatch.setattr(esports, "_load_api_key", lambda: "bad-key")
    monkeypatch.setattr(esports.requests, "get", lambda url, headers, params, timeout: _FakeResponse(status_code=401))
    result = esports.get_matches("dota2")
    assert result["matches"] == []
    assert "rejected (401)" in result["error"]


def test_get_matches_handles_429(monkeypatch):
    monkeypatch.setattr(esports, "_load_api_key", lambda: "fake-key")
    monkeypatch.setattr(esports.requests, "get", lambda url, headers, params, timeout: _FakeResponse(status_code=429))
    result = esports.get_matches("dota2")
    assert "rate limit" in result["error"]


def test_get_matches_handles_network_failure(monkeypatch):
    monkeypatch.setattr(esports, "_load_api_key", lambda: "fake-key")

    def raise_error(*a, **k):
        raise requests.ConnectionError("network down")
    monkeypatch.setattr(esports.requests, "get", raise_error)

    result = esports.get_matches("dota2")
    assert result["matches"] == []
    assert "Could not reach PandaScore" in result["error"]


def test_get_matches_handles_malformed_json(monkeypatch):
    monkeypatch.setattr(esports, "_load_api_key", lambda: "fake-key")

    class _BadJsonResponse(_FakeResponse):
        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(esports.requests, "get", lambda url, headers, params, timeout: _BadJsonResponse(status_code=200))
    result = esports.get_matches("dota2")
    assert "Could not parse" in result["error"]


def test_run_formats_multiple_games(monkeypatch):
    monkeypatch.setattr(esports, "_load_api_key", lambda: "fake-key")
    monkeypatch.setattr(
        esports.requests, "get",
        lambda url, headers, params, timeout: _FakeResponse([_raw_match()], 200),
    )
    result = esports.run("dota2")
    assert "Dota 2 upcoming:" in result
    assert "Team A vs Team B" in result


def test_run_reports_no_matches(monkeypatch):
    monkeypatch.setattr(esports, "get_matches", lambda slug, kind, limit: {"matches": [], "error": None})
    result = esports.run("dota2")
    assert "no upcoming matches" in result


def test_run_unknown_game():
    result = esports.run("overwatch")
    assert "Unknown game" in result
