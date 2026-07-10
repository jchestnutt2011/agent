import tools.stocks as stocks
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
    monkeypatch.setattr(stocks, "_quote_data", lambda symbol, label: None)
    assert run("BOGUS") == "BOGUS (BOGUS): data unavailable"


def test_load_finnhub_key_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(stocks, "FINNHUB_AUTH_FILE", tmp_path / "finnhub_auth.json")
    assert stocks._load_finnhub_key() is None


def test_load_finnhub_key_reads_api_key(tmp_path, monkeypatch):
    auth_file = tmp_path / "finnhub_auth.json"
    auth_file.write_text('{"api_key": "abc123"}', encoding="utf-8")
    monkeypatch.setattr(stocks, "FINNHUB_AUTH_FILE", auth_file)
    assert stocks._load_finnhub_key() == "abc123"


def test_quote_data_uses_finnhub_when_key_present(tmp_path, monkeypatch):
    auth_file = tmp_path / "finnhub_auth.json"
    auth_file.write_text('{"api_key": "abc123"}', encoding="utf-8")
    monkeypatch.setattr(stocks, "FINNHUB_AUTH_FILE", auth_file)
    monkeypatch.setattr(
        stocks, "_quote_data_finnhub",
        lambda symbol, label, api_key: {"symbol": symbol, "label": label, "price": 1.0,
                                          "change": 0.0, "pct_change": 0.0,
                                          "day_low": None, "day_high": None,
                                          "volume": None, "market_cap": None},
    )
    monkeypatch.setattr(stocks, "_quote_data_yfinance", lambda symbol, label: (_ for _ in ()).throw(
        AssertionError("should not fall back to yfinance when finnhub succeeds")))

    result = stocks._quote_data("AAPL", "Apple")
    assert result["price"] == 1.0


def test_quote_data_falls_back_to_yfinance_when_finnhub_fails(tmp_path, monkeypatch):
    auth_file = tmp_path / "finnhub_auth.json"
    auth_file.write_text('{"api_key": "abc123"}', encoding="utf-8")
    monkeypatch.setattr(stocks, "FINNHUB_AUTH_FILE", auth_file)
    monkeypatch.setattr(stocks, "_quote_data_finnhub", lambda symbol, label, api_key: None)
    monkeypatch.setattr(stocks, "_quote_data_yfinance", lambda symbol, label: {
        "symbol": symbol, "label": label, "price": 2.0, "change": 0.0, "pct_change": 0.0,
        "day_low": None, "day_high": None, "volume": None, "market_cap": None,
    })

    result = stocks._quote_data("AAPL", "Apple")
    assert result["price"] == 2.0


def test_quote_data_uses_yfinance_when_no_key(tmp_path, monkeypatch):
    monkeypatch.setattr(stocks, "FINNHUB_AUTH_FILE", tmp_path / "finnhub_auth.json")
    monkeypatch.setattr(stocks, "_quote_data_yfinance", lambda symbol, label: {
        "symbol": symbol, "label": label, "price": 3.0, "change": 0.0, "pct_change": 0.0,
        "day_low": None, "day_high": None, "volume": None, "market_cap": None,
    })
    result = stocks._quote_data("AAPL", "Apple")
    assert result["price"] == 3.0


def test_major_indices_relabel_as_etf_proxies_when_finnhub_configured(tmp_path, monkeypatch):
    """Finnhub's free tier has no raw index quotes, so ^GSPC etc. must be
    relabeled as their tracking ETF rather than showing the ETF's price
    under the index's name — that would be silently wrong data."""
    auth_file = tmp_path / "finnhub_auth.json"
    auth_file.write_text('{"api_key": "abc123"}', encoding="utf-8")
    monkeypatch.setattr(stocks, "FINNHUB_AUTH_FILE", auth_file)
    monkeypatch.setattr(stocks, "_quote_data_finnhub", lambda symbol, label, api_key: {
        "symbol": symbol, "label": label, "price": 550.0, "change": 1.0, "pct_change": 0.2,
        "day_low": None, "day_high": None, "volume": None, "market_cap": None,
    })

    indices = stocks.get_major_indices()

    by_label = {q["symbol"]: q["label"] for q in indices}
    assert by_label["SPY"] == "S&P 500 (SPY proxy)"
    assert by_label["DIA"] == "Dow Jones (DIA proxy)"
    assert by_label["QQQ"] == "Nasdaq (QQQ proxy)"
    assert "^GSPC" not in by_label


def test_major_indices_use_raw_symbols_without_finnhub_key(tmp_path, monkeypatch):
    monkeypatch.setattr(stocks, "FINNHUB_AUTH_FILE", tmp_path / "finnhub_auth.json")
    monkeypatch.setattr(stocks, "_quote_data_yfinance", lambda symbol, label: {
        "symbol": symbol, "label": label, "price": 5500.0, "change": 1.0, "pct_change": 0.2,
        "day_low": None, "day_high": None, "volume": None, "market_cap": None,
    })

    indices = stocks.get_major_indices()

    by_symbol = {q["symbol"]: q["label"] for q in indices}
    assert by_symbol["^GSPC"] == "S&P 500"
