import json
from datetime import datetime
from pathlib import Path

import ollama

from config import MODEL
from tools.weather import run as get_weather
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
    """Deterministic, not LLM-touched — simple enough that there's nothing to
    summarize, and it avoids any risk of the model garbling numbers."""
    return [
        f"{loc}: {_safe(f'weather for {loc}', get_weather, loc)}" for loc in config["locations"]
    ]


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
    response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return response["message"]["content"]


def _build_telegram_summary(output):
    """Compact push-notification version — full news/Reddit detail stays on
    the Streamlit dashboard, this is just enough to glance at away from home.
    Weather lines already carry any severe-alert text baked in by
    tools/weather.py's run()."""
    lines = [f"*Daily Briefing — {output['generated_at'][:10]}*", "", "*Weather:*"]
    lines += [f"- {entry}" for entry in output["weather"]]

    indices = output.get("markets", {}).get("indices", [])
    movers = [idx for idx in indices if not idx.get("error")]
    if movers:
        lines += ["", "*Markets:*"]
        lines += [
            f"- {idx['label']}: {'+' if idx['change'] >= 0 else ''}{idx['pct_change']:.2f}%"
            for idx in movers
        ]

    return "\n".join(lines)


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
