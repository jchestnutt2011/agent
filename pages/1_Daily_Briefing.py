import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).parent.parent
BRIEFING_FILE = BASE_DIR / "briefing.json"
SCRIPT = BASE_DIR / "daily_briefing.py"

st.set_page_config(page_title="Daily Briefing", page_icon="📰", layout="wide")
st.title("Daily Briefing")

if st.button("Regenerate now"):
    with st.spinner("Generating briefing... this can take a few minutes"):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=BASE_DIR, capture_output=True, text=True
        )
    if result.returncode != 0:
        st.error("Briefing generation failed. See details below.")
        st.code(result.stderr or result.stdout)
    else:
        st.rerun()

if not BRIEFING_FILE.exists():
    st.info("No briefing generated yet. Click 'Regenerate now' to create one.")
    st.stop()

data = json.loads(BRIEFING_FILE.read_text(encoding="utf-8"))
st.caption(f"Generated at {data['generated_at']}")


def _format_compact(value):
    """Abbreviate large numbers (volume, market cap) to T/B/M, no decimals below 1M."""
    if not value:
        return "—"
    if value >= 1e12:
        return f"{value / 1e12:.2f}T"
    if value >= 1e9:
        return f"{value / 1e9:.2f}B"
    if value >= 1e6:
        return f"{value / 1e6:.2f}M"
    return f"{value:,.0f}"


def quotes_to_dataframe(quotes, include_market_cap=False, sort_by_pct_change=False):
    valid = [q for q in quotes if not q.get("error")]
    errored = [q for q in quotes if q.get("error")]

    if sort_by_pct_change:
        valid = sorted(valid, key=lambda q: q["pct_change"], reverse=True)

    rows = []
    for q in valid:
        sign = "+" if q["change"] >= 0 else "-"
        row = {
            "Name": q["label"],
            "Symbol": q["symbol"],
            "Price": f"${q['price']:,.2f}",
            "Change": f"{sign}${abs(q['change']):,.2f}",
            "% Change": f"{'+' if q['pct_change'] >= 0 else ''}{q['pct_change']:.2f}%",
            "Day Range": (
                f"${q['day_low']:,.2f} - ${q['day_high']:,.2f}"
                if q.get("day_low") is not None and q.get("day_high") is not None
                else "—"
            ),
            "Volume": _format_compact(q.get("volume")),
        }
        if include_market_cap:
            row["Market Cap"] = "$" + _format_compact(q.get("market_cap")) if q.get("market_cap") else "—"
        rows.append(row)

    for q in errored:
        rows.append({"Name": q["label"], "Symbol": q.get("symbol", ""), "Price": "unavailable"})

    return pd.DataFrame(rows)


tab_weather, tab_markets, tab_news, tab_reddit = st.tabs(
    ["☀️ Weather", "📈 Markets", "📰 News", "👽 Reddit"]
)

with tab_weather:
    for line in data.get("weather", []):
        st.markdown(f"- {line}")

with tab_markets:
    markets = data.get("markets", {})

    st.subheader("Major Indices")
    indices = markets.get("indices", [])
    if indices:
        df = quotes_to_dataframe(indices)
        st.dataframe(df, hide_index=True, use_container_width=True)

    watchlist = markets.get("watchlist", [])
    if watchlist:
        st.subheader("Watchlist")
        sort_by_movers = st.toggle("Sort by % change (biggest movers first)", value=False)
        df = quotes_to_dataframe(
            watchlist, include_market_cap=True, sort_by_pct_change=sort_by_movers
        )

        def highlight_change(row):
            color = ""
            if row["% Change"].startswith("+"):
                color = "color: limegreen"
            elif row["% Change"].startswith("-"):
                color = "color: salmon"
            return [color] * len(row)

        styled = df.style.apply(highlight_change, axis=1)
        st.dataframe(styled, hide_index=True, use_container_width=True)
    else:
        st.caption("No individual tickers tracked yet — add some to briefing_config.json.")

with tab_news:
    st.markdown(data.get("news_text", "No news available."))

with tab_reddit:
    for subreddit, posts in data.get("reddit", {}).items():
        st.markdown(f"**r/{subreddit}**")
        if isinstance(posts, str):
            st.markdown(f"_{posts}_")
        else:
            for post in posts:
                st.markdown(f"- [{post['title']}]({post['url']})")

with st.expander("Raw data used for this briefing"):
    st.json(data.get("raw", {}))
