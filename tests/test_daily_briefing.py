from datetime import datetime, timezone

import daily_briefing
from daily_briefing import (
    TELEGRAM_MAX_LENGTH,
    _build_telegram_summary,
    _headlines_for,
    gather_news,
    synthesize_news,
)


def _weather_info(temperature=81.9, condition="clear sky", forecast=None, alerts=None):
    return {
        "temperature": temperature, "condition": condition,
        "forecast": forecast or [], "alerts": alerts or [],
    }


def test_build_telegram_summary_includes_weather_and_markets():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": {"Durham, NC": _weather_info()},
        "markets": {
            "indices": [
                {"label": "S&P 500", "change": 10.0, "pct_change": 0.5},
                {"label": "Dow Jones", "change": -5.0, "pct_change": -0.2},
            ],
        },
    }
    summary = _build_telegram_summary(output)

    assert "2026-07-09" in summary
    assert "Durham, NC" in summary
    assert "82°F" in summary  # 81.9 rounds to 82 for display
    assert "clear sky" in summary
    assert "S&amp;P 500: +0.50%" in summary
    assert "Dow Jones: -0.20%" in summary


def test_build_telegram_summary_includes_forecast_day_ranges():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": {
            "Durham, NC": _weather_info(forecast=[
                {"date": "2026-07-10", "high": 88.0, "low": 68.0, "precip_chance": 10},
                {"date": "2026-07-11", "high": 85.0, "low": 66.0, "precip_chance": 20},
            ]),
        },
    }
    summary = _build_telegram_summary(output)
    assert "88°/68°" in summary
    assert "85°/66°" in summary
    assert "10%" in summary


def test_build_telegram_summary_flags_active_alerts():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": {"Durham, NC": _weather_info(alerts=[{"event": "Heat Advisory"}])},
    }
    summary = _build_telegram_summary(output)
    assert "Heat Advisory" in summary
    assert "⚠️" in summary


def test_build_telegram_summary_escapes_html_in_weather_error():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": {"Durham, NC": {"error": "<script>bad</script>"}},
    }
    summary = _build_telegram_summary(output)
    assert "<script>" not in summary
    assert "&lt;script&gt;" in summary


def test_build_telegram_summary_skips_errored_indices():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": {},
        "markets": {"indices": [{"label": "S&P 500", "error": True}]},
    }
    summary = _build_telegram_summary(output)
    assert "S&P 500" not in summary


def test_build_telegram_summary_handles_no_markets_key():
    output = {"generated_at": "2026-07-09T06:00:00", "weather": {}}
    summary = _build_telegram_summary(output)
    assert "2026-07-09" in summary


def test_build_telegram_summary_includes_world_and_local_news_as_html_links():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": {},
        "news": {
            "world_news": [
                {"title": "World story", "url": "https://example.com/world"},
            ],
            "local_news": {
                "Durham, NC": [{"title": "Local story", "url": "https://example.com/local"}],
            },
        },
    }
    summary = _build_telegram_summary(output)
    assert '<a href="https://example.com/world">World story</a>' in summary
    assert '<a href="https://example.com/local">Local story</a>' in summary
    assert "World News" in summary
    assert "Durham, NC News" in summary


def test_build_telegram_summary_escapes_html_in_news_titles():
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": {},
        "news": {"world_news": [{"title": "<b>Injected</b> & co", "url": "https://example.com"}]},
    }
    summary = _build_telegram_summary(output)
    assert "<b>Injected</b>" not in summary
    assert "&lt;b&gt;Injected&lt;/b&gt; &amp; co" in summary


def test_build_telegram_summary_limits_news_items_per_section():
    many_stories = [{"title": f"Story {i}", "url": f"https://example.com/{i}"} for i in range(10)]
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": {},
        "news": {"world_news": many_stories, "local_news": {}},
    }
    summary = _build_telegram_summary(output)
    assert summary.count("<a href=") == 3


def test_build_telegram_summary_truncates_before_telegrams_hard_limit():
    """Telegram rejects the whole message over 4096 chars — a real risk since
    a single Google News redirect URL alone can run 300+ chars. Verify a
    huge day's worth of content gets truncated safely, with no dangling
    HTML tags left by cutting mid-line."""
    long_url = "https://news.google.com/rss/articles/" + "A" * 300
    many_locations = {
        f"Location {i}": {
            "temperature": 75.0, "condition": "clear sky", "forecast": [], "alerts": [],
        }
        for i in range(20)
    }
    lots_of_news = {
        f"Location {i}": [{"title": f"Story {i}", "url": long_url}] for i in range(20)
    }
    output = {
        "generated_at": "2026-07-09T06:00:00",
        "weather": many_locations,
        "news": {"world_news": [], "local_news": lots_of_news},
    }
    summary = _build_telegram_summary(output)

    assert len(summary) < 4096  # Telegram's actual hard cap
    assert summary.count("<a href=") < 20  # some were dropped
    assert summary.count("<a ") == summary.count("</a>")
    assert summary.count("<b>") == summary.count("</b>")
    assert "truncated" in summary


def test_truncate_lines_keeps_all_lines_under_budget():
    from daily_briefing import _truncate_lines

    lines = ["short line 1", "short line 2"]
    assert _truncate_lines(lines, TELEGRAM_MAX_LENGTH) == lines


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
