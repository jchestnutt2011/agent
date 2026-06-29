import json
import time
from datetime import datetime
from pathlib import Path

import ollama

from tools.weather import run as get_weather
from tools.news import run as get_news
from tools.reddit import fetch_posts as get_reddit_posts
from tools.stocks import get_major_indices, run as get_stock_quote

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "briefing_config.json"
OUTPUT_FILE = BASE_DIR / "briefing.json"
MODEL = "qwen2.5:7b-instruct"


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


def gather_raw_data(config):
    sections = {}

    sections["weather"] = [
        f"{loc}: {_safe(f'weather for {loc}', get_weather, loc)}" for loc in config["locations"]
    ]

    sections["local_news"] = [
        f"--- {loc} ---\n{_safe(f'news for {loc}', get_news, f'{loc} news')}"
        for loc in config["locations"]
    ]

    sections["world_news"] = _safe("world news", get_news, "world news")

    sections["markets"] = _safe("major indices", get_major_indices)
    if isinstance(sections["markets"], str):
        sections["markets"] = [sections["markets"]]
    if config.get("tickers"):
        sections["markets"] += [
            _safe(f"quote {t}", get_stock_quote, t) for t in config["tickers"]
        ]

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


def synthesize(raw_data):
    raw_text = json.dumps(raw_data, indent=2)
    prompt = (
        "You are writing a concise daily briefing for a person, based on the raw "
        "data below. Organize it into clear sections with short headers: Weather, "
        "Markets, and News. Keep it skimmable — use bullet points, no fluff, no "
        "repeating the raw data verbatim. Each news item includes a [YYYY-MM-DD] "
        "publish date — keep that date visible in your bullet so the reader can "
        "judge freshness. Write in Markdown.\n\n"
        f"Raw data:\n{raw_text}"
    )
    response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return response["message"]["content"]


def main():
    config = load_config()

    # Gather everything before writing anything, but never let one failing
    # step (network blip, rate limit, model error) discard data that other
    # steps already gathered successfully.
    raw_data = gather_raw_data(config)
    reddit = gather_reddit(config)
    briefing_text = _safe("briefing synthesis", synthesize, raw_data)

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "text": briefing_text,
        "reddit": reddit,
        "raw": raw_data,
    }

    # Write atomically so a crash mid-write can't corrupt the last good briefing.
    tmp_file = OUTPUT_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(OUTPUT_FILE)
    print(f"Briefing written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
