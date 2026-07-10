import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tools import esports


@pytest.fixture(autouse=True)
def _clear_streamlit_cache():
    """st.cache_data is a process-global cache keyed by function source, not
    reset between AppTest() instantiations — without this, a later test's
    monkeypatched esports.get_matches never actually runs because an
    earlier test's cached result for the same game slug is still live."""
    st.cache_data.clear()


def _match(team1="Alpha", team2="Beta"):
    return {
        "id": 1, "team1": team1, "team2": team2, "scheduled_at": "2026-07-11T09:00:00Z",
        "status": "not_started", "league": "Test League", "serie": "2026",
        "tournament": "Group A", "best_of": 3, "stream_url": "https://twitch.tv/test",
    }


def test_page_shows_setup_message_when_no_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(esports, "AUTH_FILE", tmp_path / "pandascore_auth.json")
    at = AppTest.from_file("pages/3_Esports.py")
    at.run()
    assert at.exception == []
    assert any("No PandaScore API key configured" in i.value for i in at.info)


def test_page_renders_matches_for_configured_key(tmp_path, monkeypatch):
    auth_file = tmp_path / "pandascore_auth.json"
    auth_file.write_text('{"api_key": "fake-key"}', encoding="utf-8")
    monkeypatch.setattr(esports, "AUTH_FILE", auth_file)
    monkeypatch.setattr(esports, "get_matches", lambda slug, kind, limit=8: {"matches": [_match()], "error": None})

    at = AppTest.from_file("pages/3_Esports.py")
    at.run()

    assert at.exception == []
    assert any("Alpha" in m.value and "Beta" in m.value for m in at.markdown)


def test_page_shows_warning_on_per_game_error(tmp_path, monkeypatch):
    auth_file = tmp_path / "pandascore_auth.json"
    auth_file.write_text('{"api_key": "fake-key"}', encoding="utf-8")
    monkeypatch.setattr(esports, "AUTH_FILE", auth_file)
    monkeypatch.setattr(esports, "get_matches", lambda slug, kind, limit=8: {"matches": [], "error": "rate limit hit"})

    at = AppTest.from_file("pages/3_Esports.py")
    at.run()

    assert at.exception == []
    assert any("rate limit hit" in w.value for w in at.warning)


def test_page_shows_no_matches_caption(tmp_path, monkeypatch):
    auth_file = tmp_path / "pandascore_auth.json"
    auth_file.write_text('{"api_key": "fake-key"}', encoding="utf-8")
    monkeypatch.setattr(esports, "AUTH_FILE", auth_file)
    monkeypatch.setattr(esports, "get_matches", lambda slug, kind, limit=8: {"matches": [], "error": None})

    at = AppTest.from_file("pages/3_Esports.py")
    at.run()

    assert at.exception == []
    assert any("No upcoming matches" in c.value for c in at.caption)
