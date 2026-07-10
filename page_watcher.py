"""Runs on a schedule (every 15 min via Windows Task Scheduler, alongside the
other monitors in this project). Watches configured web pages for content
changes and asks the local model whether a detected change is worth a
Telegram ping.

Config-driven, empty by default (like `locations` in briefing_config.json) —
add pages to page_watch_config.json:
    {"pages": [{"name": "...", "url": "...", "css_selector": null}]}

`css_selector` is optional. When set, only that element's text is
hashed/compared — much more precise for watching a single price or
availability element. When omitted, the whole page's visible text is used,
which has a bigger blast radius for unrelated boilerplate churn (ads,
visitor counters, relative timestamps) — the model-judgment step below is
what keeps that usable instead of notifying on every single load.

First-ever check of a page just captures a baseline silently; there's
nothing to diff against yet, so nothing to notify about.

Dedup/notify shape deliberately mirrors weather_alert_monitor.py: no hard
floor here (there's no equivalent of Severe/Extreme for an arbitrary
webpage), so every detected change goes to the local model to judge
meaningful-vs-noise. State always advances to the latest fetched content
(whether or not it was notify-worthy) so later diffs compare against what's
actually on the page now, not a stale baseline.
"""

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path

import ollama
import requests
from bs4 import BeautifulSoup

from config import MODEL
from tools import telegram_notify

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "page_watch_config.json"
STATE_FILE = BASE_DIR / "page_watch_state.json"

# A generic browser UA — some sites block the default python-requests UA
# outright, and this is just watching public pages a browser could load.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-agent home page watcher; jchestnutt2011@gmail.com)"}

# How much of the before/after text to hand the local model. Enough for it
# to judge context around a change without blowing up the prompt on a large
# page (mirrors the 600-char description truncation in weather_alert_monitor.py).
SNIPPET_CHARS = 1200


def _load_config():
    if not CONFIG_FILE.exists():
        return {"pages": []}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(state):
    tmp_file = STATE_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp_file.replace(STATE_FILE)


def _extract_text(html_content, css_selector=None):
    """Visible text only, whitespace-collapsed so incidental reformatting
    (extra newlines, indentation changes) doesn't register as a content
    change. Returns None if a css_selector was given but matched nothing —
    distinct from "" (real, deliberately empty content) so callers can tell
    a bad selector from a genuinely blank element."""
    soup = BeautifulSoup(html_content, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()

    if css_selector:
        el = soup.select_one(css_selector)
        if el is None:
            return None
        return " ".join(el.get_text(separator=" ", strip=True).split())

    return " ".join(soup.get_text(separator=" ", strip=True).split())


def _fetch_text(url, css_selector=None):
    """Returns (text, error) with error None on success — never raises, so
    one unreachable page doesn't stop the rest of the watchlist from being
    checked."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        return None, f"fetch failed: {e}"

    text = _extract_text(resp.text, css_selector)
    if text is None:
        return None, f"css_selector '{css_selector}' matched nothing"
    if not text:
        return None, "page had no extractable text"
    return text, None


def _content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ask_model_to_decide(page_name, old_text, new_text):
    """Local model judges whether a text change is meaningful (price change,
    restock, new content) versus noise (ad rotation, view counters, relative
    timestamps like "updated 3 minutes ago") that a plain hash-diff can't
    tell apart. Structured JSON output for reliable parsing from a 7B model,
    same as weather_alert_monitor.py's decision call."""
    prompt = (
        "A webpage's content changed since it was last checked. Decide "
        "whether this is a change a person watching this page would "
        "actually want to know about right now (e.g. a price change, an "
        "item back in stock, meaningful new content) versus noise that "
        "doesn't matter (an ad rotated, a view/visitor counter changed, a "
        "relative timestamp updated, unrelated boilerplate shifted). Err "
        "toward NOT notifying for noise.\n\n"
        f"Page: {page_name}\n\n"
        f"BEFORE:\n{old_text[:SNIPPET_CHARS]}\n\n"
        f"AFTER:\n{new_text[:SNIPPET_CHARS]}\n\n"
        'Respond with only JSON: {"notify": true or false, "reason": "one short sentence"}'
    )
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        decision = json.loads(response["message"]["content"])
        return bool(decision.get("notify")), str(decision.get("reason") or "no reason given")
    except Exception as e:
        # Malformed/failed model output shouldn't crash the monitor or block
        # future checks — skip this one with a clear reason and move on.
        return False, f"model decision failed, skipped as a precaution: {e}"


def _build_notification(page_name, url, reason):
    return (
        f"\U0001F310 <b>Page changed — {html.escape(page_name)}</b>\n"
        f"{html.escape(reason)}\n"
        f"{html.escape(url)}"
    )


def check():
    """Runs one monitoring pass. Returns a list of human-readable result lines."""
    config = _load_config()
    state = _load_state()
    results = []

    for page in config.get("pages", []):
        name = page["name"]
        url = page["url"]
        css_selector = page.get("css_selector")

        text, error = _fetch_text(url, css_selector)
        if error:
            results.append(f"{name}: could not check ({error})")
            continue

        new_hash = _content_hash(text)
        entry = state.get(name)

        if entry is None:
            state[name] = {
                "content_hash": new_hash,
                "content_snippet": text[:SNIPPET_CHARS],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            results.append(f"{name}: baseline captured, nothing to compare yet")
            continue

        if entry["content_hash"] == new_hash:
            results.append(f"{name}: unchanged")
            continue

        should_notify, reason = _ask_model_to_decide(name, entry.get("content_snippet", ""), text)

        if should_notify:
            sent = telegram_notify.send_message(_build_notification(name, url, reason))
            if not sent:
                results.append(f"{name}: changed and judged notify-worthy, but Telegram send failed — will retry next run")
                continue  # don't persist — retry the full decision next cycle

            results.append(f"{name}: changed — notified ({reason})")
        else:
            results.append(f"{name}: changed — skipped ({reason})")

        state[name] = {
            "content_hash": new_hash,
            "content_snippet": text[:SNIPPET_CHARS],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    _save_state(state)
    return results


def main():
    results = check()
    if not results:
        print("No pages configured to watch.")
    for line in results:
        print(line)


if __name__ == "__main__":
    main()
