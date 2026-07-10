from datetime import datetime, timezone

import daily_briefing
from daily_briefing import _build_telegram_summary, _headlines_for, gather_news, synthesize_news


def test_build_telegram_summary_includes_weather_and_markets():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": ["Durham, NC: 81.9°F, clear sky"],
        "markets": {
            "indices": [
                {"label": "S&P 500", "change": 10.0, "pct_change": 0.5},
                {"label": "Dow Jones", "change": -5.0, "pct_change": -0.2},
            ],
        },
    }
    summary = _build_telegram_summary(output)

    assert "2026-07-09" in summary
    assert "Durham, NC: 81.9°F, clear sky" in summary
    assert "S&P 500: +0.50%" in summary
    assert "Dow Jones: -0.20%" in summary


def test_build_telegram_summary_skips_errored_indices():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": [],
        "markets": {"indices": [{"label": "S&P 500", "error": True}]},
    }
    summary = _build_telegram_summary(output)
    assert "S&P 500" not in summary


def test_build_telegram_summary_handles_no_markets_key():
    output = {"generated_at": "2026-07-09T06:00:00", "weather": ["ok"]}
    summary = _build_telegram_summary(output)
    assert "ok" in summary


def _headline(title="Test story", published=None):
    return {
        "title": title, "url": "https://example.com/story", "source": "Example",
        "published": published or datetime(2026, 7, 9, tzinfo=timezone.utc),
        "body": "Details.", "image": None,
    }


def test_headlines_for_serializes_datetime_to_iso(monkeypatch):
    monkeypatch.setattr(daily_briefing, "get_headlines", lambda query, max_results: [_headline()])
    result = _headlines_for("news for X", "X news")
    assert result[0]["published"] == "2026-07-09T00:00:00+00:00"


def test_headlines_for_returns_empty_list_on_failure(monkeypatch):
    def raise_error(query, max_results):
        raise RuntimeError("network down")
    monkeypatch.setattr(daily_briefing, "get_headlines", raise_error)
    assert _headlines_for("news for X", "X news") == []


def test_gather_news_includes_locations_and_world(monkeypatch):
    monkeypatch.setattr(daily_briefing, "get_headlines", lambda query, max_results: [_headline()])
    config = {"locations": ["Durham, NC"]}
    news = gather_news(config)
    assert "Durham, NC" in news["local_news"]
    assert len(news["world_news"]) == 1
    assert "topics" not in news


def test_gather_news_includes_topics_when_configured(monkeypatch):
    monkeypatch.setattr(daily_briefing, "get_headlines", lambda query, max_results: [_headline()])
    config = {"locations": [], "topics": ["technology"]}
    news = gather_news(config)
    assert "technology" in news["topics"]


def test_synthesize_news_prompt_excludes_urls_and_dates(monkeypatch):
    captured = {}

    def fake_chat(model, messages):
        captured["prompt"] = messages[0]["content"]
        return {"message": {"content": "summary"}}

    monkeypatch.setattr(daily_briefing.ollama, "chat", fake_chat)
    news_sections = {
        "local_news": {"Durham, NC": [_headline("Local story")]},
        "world_news": [_headline("World story")],
    }
    result = synthesize_news(news_sections)

    assert result == "summary"
    assert "Local story" in captured["prompt"]
    assert "https://example.com/story" not in captured["prompt"]
    assert "2026-07-09" not in captured["prompt"]
