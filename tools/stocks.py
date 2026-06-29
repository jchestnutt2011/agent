import yfinance as yf

MAJOR_INDICES = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq Composite",
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


def _quote_data(symbol, label):
    """Structured quote: price, change, day range, volume. Returns None on failure
    so callers can decide how to represent a missing quote."""
    info = yf.Ticker(symbol).fast_info
    price = info.get("lastPrice")
    prev_close = info.get("previousClose")
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
    return [_quote_data(symbol, label) or {"symbol": symbol, "label": label, "error": True}
            for symbol, label in MAJOR_INDICES.items()]


def get_watchlist(tickers):
    """Used by the daily briefing script for arbitrary tracked tickers."""
    return [
        _quote_data(t, KNOWN_TICKER_NAMES.get(t, t)) or {"symbol": t, "label": t, "error": True}
        for t in tickers
    ]
