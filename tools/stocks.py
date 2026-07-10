import json
from pathlib import Path

import requests
import yfinance as yf

# yfinance scrapes Yahoo Finance (unofficial, prone to rate limits/IP bans).
# When finnhub_auth.json (gitignored) supplies a free-tier API key, Finnhub's
# official /quote endpoint is used instead for real stock/ETF tickers, with
# yfinance kept as the automatic fallback if no key is configured or a
# Finnhub call fails.
FINNHUB_AUTH_FILE = Path(__file__).parent.parent / "finnhub_auth.json"

MAJOR_INDICES = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq Composite",
}

# Finnhub's free tier has no raw index quotes ("essentially monopolized" data
# per their own docs) — the standard workaround is pricing the tracking ETF
# instead. We label these honestly as the ETF, not the index itself, since
# the ETF's price doesn't match the index's absolute value (though its %
# change closely tracks it).
FINNHUB_INDEX_PROXIES = {
    "^GSPC": ("SPY", "S&P 500 (SPY proxy)"),
    "^DJI": ("DIA", "Dow Jones (DIA proxy)"),
    "^IXIC": ("QQQ", "Nasdaq (QQQ proxy)"),
}

# Friendly names for common tickers so the briefing doesn't just show bare
# symbols. Falls back to the symbol itself for anything not listed here —
# avoids an extra slow API call (yfinance's full .info) just for a label.
KNOWN_TICKER_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    "META": "Meta",
    "TSLA": "Tesla",
    "NFLX": "Netflix",
    "AMD": "AMD",
}

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_stock_quote",
        "description": "Get the current price and daily change for a stock ticker or index symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol, e.g. 'AAPL' or '^GSPC' for S&P 500"}
            },
            "required": ["ticker"],
        },
    },
}


def _load_finnhub_key():
    if not FINNHUB_AUTH_FILE.exists():
        return None
    try:
        data = json.loads(FINNHUB_AUTH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data.get("api_key") or None


def _quote_data_yfinance(symbol, label):
    """Structured quote: price, change, day range, volume. Returns None on failure
    so callers can decide how to represent a missing quote."""
    try:
        info = yf.Ticker(symbol).fast_info
        price = info.get("lastPrice")
        prev_close = info.get("previousClose")
    except Exception:
        return None
    if price is None or prev_close is None:
        return None

    change = price - prev_close
    pct_change = (change / prev_close) * 100 if prev_close else 0

    return {
        "symbol": symbol,
        "label": label,
        "price": price,
        "change": change,
        "pct_change": pct_change,
        "day_low": info.get("dayLow"),
        "day_high": info.get("dayHigh"),
        "volume": info.get("lastVolume"),
        "market_cap": info.get("marketCap"),
    }


def _quote_data_finnhub(symbol, label, api_key):
    """Same shape as _quote_data_yfinance. Finnhub's free /quote endpoint has
    no volume or market cap fields, so those come back None (already handled
    as '—' by the UI)."""
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    price = data.get("c")
    prev_close = data.get("pc")
    if not price or not prev_close:
        return None

    change = data.get("d")
    if change is None:
        change = price - prev_close
    pct_change = data.get("dp")
    if pct_change is None:
        pct_change = (change / prev_close) * 100 if prev_close else 0

    return {
        "symbol": symbol,
        "label": label,
        "price": price,
        "change": change,
        "pct_change": pct_change,
        "day_low": data.get("l"),
        "day_high": data.get("h"),
        "volume": None,
        "market_cap": None,
    }


def _quote_data(symbol, label):
    api_key = _load_finnhub_key()
    if api_key:
        result = _quote_data_finnhub(symbol, label, api_key)
        if result is not None:
            return result
    return _quote_data_yfinance(symbol, label)


def _format_quote(q):
    if q is None:
        return None
    direction = "+" if q["change"] >= 0 else ""
    line = (
        f"{q['label']} ({q['symbol']}): ${q['price']:.2f} "
        f"({direction}{q['change']:.2f}, {direction}{q['pct_change']:.2f}%)"
    )
    if q["day_low"] is not None and q["day_high"] is not None:
        line += f", day range ${q['day_low']:.2f}-${q['day_high']:.2f}"
    return line


def run(ticker):
    label = MAJOR_INDICES.get(ticker, ticker)
    line = _format_quote(_quote_data(ticker, label))
    return line or f"{label} ({ticker}): data unavailable"


def get_major_indices():
    """Used by the daily briefing script; not exposed as a chat tool."""
    use_proxies = bool(_load_finnhub_key())
    results = []
    for symbol, label in MAJOR_INDICES.items():
        request_symbol, request_label = (
            FINNHUB_INDEX_PROXIES[symbol] if use_proxies else (symbol, label)
        )
        quote = _quote_data(request_symbol, request_label)
        results.append(quote or {"symbol": request_symbol, "label": request_label, "error": True})
    return results


def get_watchlist(tickers):
    """Used by the daily briefing script for arbitrary tracked tickers."""
    return [
        _quote_data(t, KNOWN_TICKER_NAMES.get(t, t)) or {"symbol": t, "label": t, "error": True}
        for t in tickers
    ]
