from daily_briefing import _build_telegram_summary


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
