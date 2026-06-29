import json
import time
from datetime import datetime
from pathlib import Path

import ollama

from tools.weather import run as get_weather
from tools.news import run as get_news
from tools.reddit import run as get_reddit_top
from tools.stocks import get_major_indices, run as get_stock_quote

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "briefing_config.json"
OUTPUT_FILE = BASE_DIR / "briefing.json"
MODEL = "qwen2.5:7b-instruct"


def load_config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def gather_raw_data(config):
    sections = {}

    sections["weather"] = [
        f"{loc}: {get_weather(loc)}" for loc in config["locations"]
    ]

    sections["local_news"] = [
        f"--- {loc} ---\n{get_news(f'{loc} news')}" for loc in config["locations"]
    ]

    sections["world_news"] = get_news("world news")

    sections["markets"] = get_major_indices()
    if config.get("tickers"):
        sections["markets"] += [get_stock_quote(t) for t in config["tickers"]]

    sections["reddit"] = []
    for i, sub in enumerate(config["subreddits"]):
        if i > 0:
            time.sleep(3)
        sections["reddit"].append(get_reddit_top(sub))

    return sections


def synthesize(raw_data):
    raw_text = json.dumps(raw_data, indent=2)
    prompt = (
        "You are writing a concise daily briefing for a person, based on the raw "
        "data below. Organize it into clear sections with short headers: Weather, "
        "Markets, News, and Reddit Highlights. Keep it skimmable — use bullet points, "
        "no fluff, no repeating the raw data verbatim. Write in Markdown.\n\n"
        f"Raw data:\n{raw_text}"
    )
    response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return response["message"]["content"]


def main():
    config = load_config()
    raw_data = gather_raw_data(config)
    briefing_text = synthesize(raw_data)

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "text": briefing_text,
        "raw": raw_data,
    }
    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Briefing written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
