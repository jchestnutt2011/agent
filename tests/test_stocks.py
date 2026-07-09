from tools.stocks import _format_quote, run


def test_format_quote_positive_change():
    quote = {
        "symbol": "AAPL", "label": "Apple", "price": 210.5, "change": 1.25,
        "pct_change": 0.6, "day_low": 208.0, "day_high": 211.0,
    }
    line = _format_quote(quote)
    assert "Apple (AAPL): $210.50" in line
    assert "+1.25" in line
    assert "+0.60%" in line
    assert "day range $208.00-$211.00" in line


def test_format_quote_negative_change_has_no_plus_sign():
    quote = {
        "symbol": "TSLA", "label": "Tesla", "price": 180.0, "change": -3.4,
        "pct_change": -1.85, "day_low": None, "day_high": None,
    }
    line = _format_quote(quote)
    assert "-3.40" in line
    assert "-1.85%" in line
    assert "+" not in line
    assert "day range" not in line


def test_format_quote_none_returns_none():
    assert _format_quote(None) is None


def test_run_falls_back_to_unavailable_message(monkeypatch):
    import tools.stocks as stocks
    monkeypatch.setattr(stocks, "_quote_data", lambda symbol, label: None)
    assert run("BOGUS") == "BOGUS (BOGUS): data unavailable"
