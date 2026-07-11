import html
import json
from datetime import datetime
from pathlib import Path

import ollama

from config import KEEP_ALIVE, MODEL, NUM_CTX
from tools.weather import get_conditions
from tools.news import fetch_headlines as get_headlines
from tools.reddit import fetch_posts as get_reddit_posts
from tools.stocks import get_major_indices, get_watchlist
from tools import telegram_notify

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "briefing_config.json"
OUTPUT_FILE = BASE_DIR / "briefing.json"


def load_config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _safe(label, fn, *args):
    """Run a data-gathering step without letting one failure take down the whole
    briefing. Network blips, rate limits, or upstream outages on one source
    shouldn't cost us everything else that succeeded."""
    try:
        return fn(*args)
    except Exception as e:
        print(f"[warn] {label} failed: {e}")
        return f"{label} unavailable: {e}"


def gather_weather(config):
    """Structured per-location conditions + forecast (used to build the
    Telegram day-range summary). Deterministic, not LLM-touched — same
    reasoning as markets: no risk of the model garbling numbers. The
    Streamlit Weather tab fetches its own live copy independently, so this
    snapshot doesn't need to match that shape exactly."""
    result = {}
    for loc in config["locations"]:
        info = _safe(f"weather for {loc}", get_conditions, loc)
        result[loc] = info if isinstance(info, dict) else {"error": info}
    return result


def gather_markets(config):
    """Deterministic structured data, not LLM-touched — same reasoning as Reddit:
    a small local model has no business rewriting prices and percentages."""
    indices = _safe("major indices", get_major_indices)
    if isinstance(indices, str):
        indices = [{"label": "major indices", "error": True, "message": indices}]

    watchlist = []
    if config.get("tickers"):
        watchlist = _safe("ticker watchlist", get_watchlist, config["tickers"])
        if isinstance(watchlist, str):
            watchlist = [{"label": "watchlist", "error": True, "message": watchlist}]

    return {"indices": indices, "watchlist": watchlist}


def _headlines_for(label, query, max_results=6):
    """Structured headlines with datetimes serialized to ISO strings so the
    result is directly JSON-writable (and directly renderable in the
    Streamlit page, unlike the old LLM-only text blob)."""
    headlines = _safe(label, get_headlines, query, max_results)
    if isinstance(headlines, str):
        return []
    return [{**h, "published": h["published"].isoformat()} for h in headlines]


def gather_news(config):
    """Structured per-section headlines (title/url/source/date/body/image) —
    rendered directly in the Streamlit News tab so links are always correct,
    never at the mercy of the local model reproducing them faithfully."""
    sections = {
        "local_news": {
            loc: _headlines_for(f"news for {loc}", f"{loc} news") for loc in config["locations"]
        },
        "world_news": _headlines_for("world news", "world news"),
    }
    if config.get("topics"):
        sections["topics"] = {
            topic: _headlines_for(f"news for topic '{topic}'", topic) for topic in config["topics"]
        }
    return sections


def gather_reddit(config):
    """Kept separate from the LLM-synthesized sections: rendered as-is (title + link)
    so every subreddit is guaranteed to show up, with no risk of the model dropping
    or rewriting entries during summarization."""
    return {sub: _safe(f"r/{sub}", get_reddit_posts, sub) for sub in config["subreddits"]}


def synthesize_news(news_sections):
    """A short skimmable narrative, NOT a link list — the actual headlines
    with working links are rendered directly from structured data in the
    Streamlit page, so the model doesn't need to (and shouldn't try to)
    reproduce titles/URLs faithfully. This is just the "what's going on"
    framing text above that list."""
    condensed = {
        section: (
            {k: [h["title"] for h in v] for k, v in value.items()}
            if isinstance(value, dict) else [h["title"] for h in value]
        )
        for section, value in news_sections.items()
    }
    raw_text = json.dumps(condensed, indent=2)
    prompt = (
        "Here are today's news headlines (grouped by location/topic, plus world "
        "news) — titles only, no links or dates. Write a short, skimmable "
        "narrative summary (a few sentences per group, not a bullet-by-bullet "
        "restatement) covering what's going on. The full headline list with "
        "working links is shown separately right after your summary, so don't "
        "try to enumerate every headline or include URLs — just give the "
        "reader the gist. Write in Markdown with a short header per group.\n\n"
        f"Headlines:\n{raw_text}"
    )
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        keep_alive=KEEP_ALIVE,
        options={"num_ctx": NUM_CTX},
    )
    return response["message"]["content"]


def _format_forecast_day(day):
    date_label = datetime.fromisoformat(day["date"]).strftime("%a")
    rain = f" {day['precip_chance']}%\U0001F327" if day.get("precip_chance") else ""
    return f"{date_label} {day['high']:.0f}°/{day['low']:.0f}°{rain}"


def _format_weather_entry(loc, info):
    loc_safe = html.escape(loc)
    if info.get("error"):
        return f"<b>{loc_safe}</b>: {html.escape(str(info['error']))}"

    parts = [f"<b>{loc_safe}</b> — {info['temperature']:.0f}°F, {html.escape(info['condition'])}"]
    parts += [f"⚠️ {html.escape(alert['event'])}" for alert in (info.get("alerts") or [])]

    forecast = info.get("forecast", [])
    if forecast:
        parts.append(" · ".join(_format_forecast_day(day) for day in forecast))

    return "\n".join(parts)


def _format_news_link(item):
    title = html.escape(item["title"])
    url = html.escape(item["url"], quote=True)
    return f'- <a href="{url}">{title}</a>'


# Telegram hard-rejects any message over 4096 chars (the whole send fails,
# taking weather down with it). Google News redirect URLs alone can run
# 300+ chars, so a busy news day gets uncomfortably close to that — leave
# real headroom rather than cutting it close.
TELEGRAM_MAX_LENGTH = 4000


def _truncate_lines(lines, max_length):
    """Drop trailing lines once the joined text would exceed max_length.
    Line-level, not character-level: every line built by this module is a
    complete, self-closed HTML fragment (a full <a>...</a> or <b>...</b>),
    so cutting between lines can never leave a dangling tag — cutting
    mid-line could."""
    kept, total = [], 0
    for line in lines:
        total += len(line) + 1  # +1 for the newline that'll join it
        if total > max_length:
            kept.append("\n… (truncated — see the dashboard for full details)")
            return kept
        kept.append(line)
    return kept


def _build_telegram_summary(output):
    """Compact push-notification version — full detail (raw headline bodies,
    thumbnails, Reddit) stays on the Streamlit dashboard; this is just enough
    to glance at away from home. HTML parse mode, not Markdown: headline
    titles are external, uncontrolled text, and Markdown breaks the whole
    message on an unescaped _/*/[, whereas HTML only needs </>/& escaped."""
    lines = [f"<b>Daily Briefing — {output['generated_at'][:10]}</b>"]

    weather = output.get("weather", {})
    if weather:
        lines += ["", "<b>Weather:</b>"]
        lines += [_format_weather_entry(loc, info) for loc, info in weather.items()]

    indices = output.get("markets", {}).get("indices", [])
    movers = [idx for idx in indices if not idx.get("error")]
    if movers:
        lines += ["", "<b>Markets:</b>"]
        lines += [
            f"- {html.escape(idx['label'])}: {'+' if idx['change'] >= 0 else ''}{idx['pct_change']:.2f}%"
            for idx in movers
        ]

    news = output.get("news", {})

    world_news = news.get("world_news", [])
    if world_news:
        lines += ["", "<b>World News:</b>"]
        lines += [_format_news_link(item) for item in world_news[:3]]

    for loc, headlines in news.get("local_news", {}).items():
        if headlines:
            lines += ["", f"<b>{html.escape(loc)} News:</b>"]
            lines += [_format_news_link(item) for item in headlines[:2]]

    return "\n".join(_truncate_lines(lines, TELEGRAM_MAX_LENGTH))


def main():
    config = load_config()

    # Gather everything before writing anything, but never let one failing
    # step (network blip, rate limit, model error) discard data that other
    # steps already gathered successfully.
    weather = gather_weather(config)
    markets = gather_markets(config)
    news = gather_news(config)
    reddit = gather_reddit(config)
    news_text = _safe("news synthesis", synthesize_news, news)

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weather": weather,
        "markets": markets,
        "news_text": news_text,
        "news": news,
        "reddit": reddit,
    }

    # Write atomically so a crash mid-write can't corrupt the last good briefing.
    tmp_file = OUTPUT_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(OUTPUT_FILE)
    print(f"Briefing written to {OUTPUT_FILE}")

    sent = _safe("telegram notification", lambda: telegram_notify.send_message(_build_telegram_summary(output)))
    if sent is True:
        print("Telegram notification sent.")


if __name__ == "__main__":
    main()
