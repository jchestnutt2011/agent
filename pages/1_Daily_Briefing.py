import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from tools.stocks import get_major_indices, get_watchlist
from tools.weather import get_conditions

BASE_DIR = Path(__file__).parent.parent
BRIEFING_FILE = BASE_DIR / "briefing.json"
CONFIG_FILE = BASE_DIR / "briefing_config.json"
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


@st.cache_data(ttl=900)
def fetch_live_weather(locations):
    """Cached for 15 minutes, same reasoning as markets — cheap to fetch live,
    no reason to wait for the once-daily snapshot. Returns a dict per location,
    each either real conditions or an {'error': ...} dict — never raises, so a
    single bad/unreachable location can't take down the whole tab."""
    results = {}
    for loc in locations:
        try:
            results[loc] = get_conditions(loc)
        except Exception as e:
            results[loc] = {"error": f"Unexpected error fetching weather for {loc}: {e}"}
    return results


@st.fragment(run_every="15m")
def render_weather_tab():
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    locations = config.get("locations", [])

    refresh_col, _ = st.columns([1, 4])
    with refresh_col:
        if st.button("Refresh now", key="refresh_weather"):
            fetch_live_weather.clear()
            st.rerun(scope="fragment")
    st.caption("Live — auto-refreshes every 15 minutes while this page is open")

    if not locations:
        st.caption("No locations configured yet — add some to briefing_config.json.")
        return

    weather = fetch_live_weather(tuple(locations))

    for loc in locations:
        info = weather.get(loc, {})
        st.subheader(loc)

        if "error" in info:
            st.warning(info["error"])
            continue

        for alert in info.get("alerts") or []:
            severity = (alert.get("severity") or "").lower()
            banner = st.error if severity in ("severe", "extreme") else st.warning
            banner(f"**{alert['event']}**: {alert.get('headline') or ''}")

        cols = st.columns(4)
        cols[0].metric("Temperature", f"{info['temperature']:.0f}°F")
        if info.get("feels_like") is not None:
            cols[1].metric("Feels Like", f"{info['feels_like']:.0f}°F")
        if info.get("humidity") is not None:
            cols[2].metric("Humidity", f"{info['humidity']}%")
        if info.get("wind_speed") is not None:
            direction = f" {info['wind_direction']}" if info.get("wind_direction") else ""
            cols[3].metric("Wind", f"{info['wind_speed']:.0f} mph{direction}")
        st.caption(info["condition"].capitalize())

        forecast = info.get("forecast", [])
        if forecast:
            rows = []
            for day in forecast:
                rows.append({
                    "Date": day["date"],
                    "Condition": day["condition"].capitalize(),
                    "High": f"{day['high']:.0f}°F",
                    "Low": f"{day['low']:.0f}°F",
                    "Rain Chance": f"{day['precip_chance']}%",
                    "UV Index": f"{day['uv_index']:.1f}",
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')


@st.cache_data(ttl=900)
def fetch_live_markets(tickers):
    """Cached for 15 minutes — independent of the once-daily briefing snapshot,
    since market data is cheap to fetch live (unlike Reddit/news, which are slow
    and rate-limited)."""
    return {
        "indices": get_major_indices(),
        "watchlist": get_watchlist(list(tickers)) if tickers else [],
    }


@st.fragment(run_every="15m")
def render_markets_tab():
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    markets = fetch_live_markets(tuple(config.get("tickers", [])))

    refresh_col, _ = st.columns([1, 4])
    with refresh_col:
        if st.button("Refresh now", key="refresh_markets"):
            fetch_live_markets.clear()
            st.rerun(scope="fragment")
    st.caption("Live — auto-refreshes every 15 minutes while this page is open")

    st.subheader("Major Indices")
    indices = markets.get("indices", [])
    if indices:
        df = quotes_to_dataframe(indices)
        st.dataframe(df, hide_index=True, width='stretch')

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
        st.dataframe(styled, hide_index=True, width='stretch')
    else:
        st.caption("No individual tickers tracked yet — add some to briefing_config.json.")


def render_headline(item):
    """One story: optional thumbnail, clickable title, source + date, and a
    snippet when one's available (Google-sourced items have no snippet)."""
    date_str = item["published"][:10]
    if item.get("image"):
        img_col, text_col = st.columns([1, 5])
        with img_col:
            st.image(item["image"], width='stretch')
    else:
        text_col = st.container()

    with text_col:
        st.markdown(f"**[{item['title']}]({item['url']})**")
        caption = item["source"] or "Unknown source"
        if date_str:
            caption += f" · {date_str}"
        st.caption(caption)
        if item.get("body"):
            st.caption(item["body"])


def render_news_section(header, headlines):
    if not headlines:
        return
    st.subheader(header)
    for item in headlines:
        render_headline(item)


tab_weather, tab_markets, tab_news, tab_reddit = st.tabs(
    ["☀️ Weather", "📈 Markets", "📰 News", "👽 Reddit"]
)

with tab_weather:
    render_weather_tab()

with tab_markets:
    render_markets_tab()

with tab_news:
    st.markdown(data.get("news_text", "No news available."))
    st.divider()

    news = data.get("news", {})
    for loc, headlines in news.get("local_news", {}).items():
        render_news_section(loc, headlines)
    render_news_section("World News", news.get("world_news", []))
    for topic, headlines in news.get("topics", {}).items():
        render_news_section(f"Topic: {topic}", headlines)

with tab_reddit:
    for subreddit, posts in data.get("reddit", {}).items():
        st.markdown(f"**r/{subreddit}**")
        if isinstance(posts, str):
            st.markdown(f"_{posts}_")
        else:
            for post in posts:
                st.markdown(f"- [{post['title']}]({post['url']})")

with st.expander("Raw data used for this briefing"):
    st.json(data.get("news", {}))
