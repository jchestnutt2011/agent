import yfinance as yf

MAJOR_INDICES = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq Composite",
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


def _quote_line(symbol, label):
    info = yf.Ticker(symbol).fast_info
    price = info.get("lastPrice")
    prev_close = info.get("previousClose")
    if price is None or prev_close is None:
        return f"{label} ({symbol}): data unavailable"
    change = price - prev_close
    pct = (change / prev_close) * 100 if prev_close else 0
    direction = "+" if change >= 0 else ""
    return f"{label} ({symbol}): {price:.2f} ({direction}{change:.2f}, {direction}{pct:.2f}%)"


def run(ticker):
    label = MAJOR_INDICES.get(ticker, ticker)
    return _quote_line(ticker, label)


def get_major_indices():
    """Used by the daily briefing script; not exposed as a chat tool."""
    return [_quote_line(symbol, label) for symbol, label in MAJOR_INDICES.items()]
