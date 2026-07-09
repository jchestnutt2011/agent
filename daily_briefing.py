import json
import time
from datetime import datetime
from pathlib import Path

import ollama

from config import MODEL
from tools.weather import run as get_weather
from tools.news import run as get_news
from tools.reddit import fetch_posts as get_reddit_posts
from tools.stocks import get_major_indices, get_watchlist

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


def gather_news_raw(config):
    sections = {}
    sections["local_news"] = {
        loc: _safe(f"news for {loc}", get_news, f"{loc} news") for loc in config["locations"]
    }
    sections["world_news"] = _safe("world news", get_news, "world news")
    return sections


def gather_reddit(config):
    """Kept separate from the LLM-synthesized sections: rendered as-is (title + link)
    so every subreddit is guaranteed to show up, with no risk of the model dropping
    or rewriting entries during summarization."""
    reddit = {}
    for i, sub in enumerate(config["subreddits"]):
        if i > 0:
            time.sleep(10)
        reddit[sub] = _safe(f"r/{sub}", get_reddit_posts, sub)
    return reddit


def synthesize_news(news_raw):
    raw_text = json.dumps(news_raw, indent=2)
    prompt = (
        "You are writing the News section of a daily briefing, based on the raw "
        "headlines below (grouped by location, plus world news). Organize it with "
        "a short header per location/world. Keep it skimmable — bullet points, no "
        "fluff, no repeating the raw text verbatim. Each item includes a "
        "[YYYY-MM-DD] publish date — keep that date visible in your bullet so the "
        "reader can judge freshness. Write in Markdown.\n\n"
        f"Raw headlines:\n{raw_text}"
    )
    response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return response["message"]["content"]


def main():
    config = load_config()

    # Gather everything before writing anything, but never let one failing
    # step (network blip, rate limit, model error) discard data that other
    # steps already gathered successfully.
    weather = gather_weather(config)
    markets = gather_markets(config)
    news_raw = gather_news_raw(config)
    reddit = gather_reddit(config)
    news_text = _safe("news synthesis", synthesize_news, news_raw)

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weather": weather,
        "markets": markets,
        "news_text": news_text,
        "reddit": reddit,
        "raw": {"news": news_raw},
    }

    # Write atomically so a crash mid-write can't corrupt the last good briefing.
    tmp_file = OUTPUT_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(OUTPUT_FILE)
    print(f"Briefing written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
