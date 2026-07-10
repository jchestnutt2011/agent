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

Price mode — a page with `price_threshold_pct` set is watched differently:
notify is a deterministic percent-change threshold, NOT the local model.
Same reasoning as daily_briefing.py's gather_markets(): a small local model
has no business rewriting prices, and a threshold check is exact where a
model judgment call would just add noise/latency. Also throttled by
`check_interval_minutes` (default 4h, NOT this script's 15-min cadence) —
a site like Amazon serving a CAPTCHA instead of the real page to a request
pattern it doesn't like is a real, observed risk (see _looks_blocked), and
prices don't need 15-minute granularity anyway.
"""

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import ollama
import requests
from bs4 import BeautifulSoup

import state_store
from config import MODEL
from tools import telegram_notify
from tools.http_headers import BROWSER_HEADERS

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "page_watch_config.json"
STATE_FILE = BASE_DIR / "page_watch_state.json"

# How much of the before/after text to hand the local model. Enough for it
# to judge context around a change without blowing up the prompt on a large
# page (mirrors the 600-char description truncation in weather_alert_monitor.py).
SNIPPET_CHARS = 1200

PRICE_PATTERN = re.compile(r"\$\s?([\d,]+\.\d{2})")

DEFAULT_PRICE_CHECK_INTERVAL_MINUTES = 240

# A single check-to-check ratio outside this band is treated as a probable
# extraction error (grabbed the wrong element — a shipping fee, a bundled
# accessory, an unrelated sponsored item) rather than a real price move,
# even for a page with a generous notify threshold. Real prices essentially
# never jump 5x or drop to a fifth of their previous value between two
# checks 15 minutes to 4 hours apart; a wrong-element grab easily produces
# exactly that.
PLAUSIBLE_PRICE_RATIO = (0.2, 5.0)

# Phrases Amazon's anti-bot page actually contains — seen live when a bare
# User-Agent-only request was blocked. A false "blocked" positive just
# means one skipped check; a false negative would misread a CAPTCHA page's
# absence of a price as "no price found," so this check runs first.
BLOCK_MARKERS = (
    "api-services-support@amazon.com",
    "Enter the characters you see below",
    "Type the characters you see in this image",
)


def _load_config():
    if not CONFIG_FILE.exists():
        return {"pages": []}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _load_state():
    return state_store.load_json_state(STATE_FILE)


def _save_state(state):
    state_store.save_json_state(STATE_FILE, state)


def _extract_text(content, css_selector=None, is_xml=False):
    """Visible text only, whitespace-collapsed so incidental reformatting
    (extra newlines, indentation changes) doesn't register as a content
    change. Returns None if a css_selector was given but matched nothing —
    distinct from "" (real, deliberately empty content) so callers can tell
    a bad selector from a genuinely blank element.

    is_xml picks lxml's XML parser instead of its (lenient, tag-soup-
    tolerant) HTML parser — needed for real RSS/Atom feeds like a game's
    Steam news feed, which many real sites publish patch notes through and
    which this project's own patch-note watches rely on. The HTML parser
    still works on an XML feed (bs4 warns, doesn't fail), but the XML
    parser handles the document structure correctly instead of by luck."""
    parser = "xml" if is_xml else "lxml"
    soup = BeautifulSoup(content, parser)
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
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        return None, f"fetch failed: {e}"

    is_xml = "xml" in resp.headers.get("Content-Type", "").lower()
    text = _extract_text(resp.text, css_selector, is_xml=is_xml)
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


def _looks_blocked(html_content):
    return any(marker in html_content for marker in BLOCK_MARKERS)


def _extract_price(html_content, css_selector=None):
    """Best-effort price extraction. Returns a float or None (never raises).

    If css_selector is given, that element's text is the only place searched
    — the reliable option when auto-detection doesn't land on the right
    number for a given site.

    Auto-detection (no selector) tries, in order:
    1. Amazon's buybox price JSON, embedded in a `.twister-plus-buying-
       options-price-data` element. Verified against a real product page —
       necessary because the page also embeds `priceAmount` fields for
       several unrelated sponsored/related products, so a naive "first
       priceAmount on the page" grab picks up the wrong item entirely.
    2. Amazon's core price display widget's first non-empty offscreen price
       text (the accessible/screen-reader price string).
    3. Generic fallback for non-Amazon sites: the first dollar-amount-shaped
       string anywhere in the page's visible text. Least precise — prefer a
       css_selector for anything where this could grab the wrong number
       (e.g. a "was $X" strikethrough price appearing before the real one).
    """
    soup = BeautifulSoup(html_content, "lxml")

    if css_selector:
        el = soup.select_one(css_selector)
        if el is None:
            return None
        match = PRICE_PATTERN.search(el.get_text(" ", strip=True))
        return float(match.group(1).replace(",", "")) if match else None

    twister_div = soup.select_one(".twister-plus-buying-options-price-data")
    if twister_div:
        try:
            data = json.loads(twister_div.get_text())
            for group in data.values():
                if group and "priceAmount" in group[0]:
                    return float(group[0]["priceAmount"])
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            pass

    for container_id in ("#corePriceDisplay_desktop_feature_div", "#corePrice_feature_div", "#apex_desktop"):
        container = soup.select_one(container_id)
        if container is None:
            continue
        for offscreen in container.select(".a-price .a-offscreen"):
            match = PRICE_PATTERN.search(offscreen.get_text(strip=True))
            if match:
                return float(match.group(1).replace(",", ""))

    match = PRICE_PATTERN.search(soup.get_text(" ", strip=True))
    return float(match.group(1).replace(",", "")) if match else None


def _is_plausible_price(reference_price, new_price):
    low, high = PLAUSIBLE_PRICE_RATIO
    return low <= (new_price / reference_price) <= high


def _build_price_notification(name, url, old_price, new_price, pct_change):
    direction = "dropped" if pct_change < 0 else "risen"
    icon = "\U0001F4C9" if pct_change < 0 else "\U0001F4C8"
    return (
        f"{icon} <b>Price {direction} — {html.escape(name)}</b>\n"
        f"${old_price:.2f} → ${new_price:.2f} ({pct_change:+.1f}%)\n"
        f"{html.escape(url)}"
    )


def _check_price_page(name, url, css_selector, threshold_pct, interval_minutes, state):
    """Deterministic percent-change price check — mutates `state[name]` in
    place and returns a human-readable result line. See module docstring for
    why this doesn't use the local model or this script's usual 15-min cadence.
    An implausible price jump (see _is_plausible_price) is treated like a
    fetch error: logged, not notified, state left untouched so the next
    cycle retries against the same reference rather than resetting to a
    probably-wrong number."""
    now = datetime.now(timezone.utc)
    entry = state.get(name)

    if entry and entry.get("last_checked_at"):
        minutes_since = (now - datetime.fromisoformat(entry["last_checked_at"])).total_seconds() / 60
        if minutes_since < interval_minutes:
            return f"{name}: skipped (checked {minutes_since:.0f} min ago, interval is {interval_minutes} min)"

    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        return f"{name}: could not check (fetch failed: {e})"

    if _looks_blocked(resp.text):
        return f"{name}: could not check (page looks like an anti-bot/CAPTCHA block, not the real product page)"

    price = _extract_price(resp.text, css_selector)
    if price is None:
        return f"{name}: could not check (no price found on page — consider setting a css_selector)"

    if entry is None or entry.get("reference_price") is None:
        state[name] = {"reference_price": price, "last_price": price, "last_checked_at": now.isoformat()}
        return f"{name}: baseline captured (${price:.2f}), nothing to compare yet"

    reference_price = entry["reference_price"]

    if not _is_plausible_price(reference_price, price):
        return (
            f"{name}: extracted price ${price:.2f} looks implausible next to reference "
            f"${reference_price:.2f} (likely grabbed the wrong element) — skipping, "
            "not updating state; will retry next cycle"
        )

    pct_change = (price - reference_price) / reference_price * 100

    if abs(pct_change) >= threshold_pct:
        sent = telegram_notify.send_message(_build_price_notification(name, url, reference_price, price, pct_change))
        if not sent:
            return (
                f"{name}: price moved {pct_change:+.1f}% (${reference_price:.2f} -> ${price:.2f}) "
                "but Telegram send failed — will retry next run"
            )
        # Reset the reference point to the new price so a further move (in
        # either direction) from here can be caught too.
        state[name] = {"reference_price": price, "last_price": price, "last_checked_at": now.isoformat()}
        return f"{name}: price moved {pct_change:+.1f}% (${reference_price:.2f} -> ${price:.2f}) — notified"

    state[name] = {"reference_price": reference_price, "last_price": price, "last_checked_at": now.isoformat()}
    return f"{name}: price ${price:.2f} ({pct_change:+.1f}% from reference ${reference_price:.2f}) — below {threshold_pct}% threshold"


def _check_content_page(name, url, css_selector, state):
    """Content-diff + local-model-judged check for one page — mutates
    `state[name]` in place and returns a human-readable result line. Split
    out from check() so each page's dispatch is a single function call with
    no early `continue`s, which lets check() reliably detect whether a given
    page's state entry actually changed (see the touched-entries comment
    there) regardless of which branch returned."""
    text, error = _fetch_text(url, css_selector)
    if error:
        return f"{name}: could not check ({error})"

    new_hash = _content_hash(text)
    entry = state.get(name)

    if entry is None:
        state[name] = {
            "content_hash": new_hash,
            "content_snippet": text[:SNIPPET_CHARS],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        return f"{name}: baseline captured, nothing to compare yet"

    if entry["content_hash"] == new_hash:
        return f"{name}: unchanged"

    should_notify, reason = _ask_model_to_decide(name, entry.get("content_snippet", ""), text)

    if should_notify:
        sent = telegram_notify.send_message(_build_notification(name, url, reason))
        if not sent:
            return f"{name}: changed and judged notify-worthy, but Telegram send failed — will retry next run"
        result = f"{name}: changed — notified ({reason})"
    else:
        result = f"{name}: changed — skipped ({reason})"

    state[name] = {
        "content_hash": new_hash,
        "content_snippet": text[:SNIPPET_CHARS],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return result


def check():
    """Runs one monitoring pass. Returns a list of human-readable result lines.

    State is merged, not blindly overwritten: this loop can take a while
    (fetching several real pages), and page_watch_state.json is also
    written by the Streamlit price-watch UI. Saving this call's full
    in-memory snapshot at the end would silently clobber any edit the UI
    made mid-run. Instead, only pages whose entry actually changed this
    pass are merged onto whatever's on disk at merge time — see
    state_store.merge_json_state."""
    config = _load_config()
    state = _load_state()
    results = []
    touched = {}

    for page in config.get("pages", []):
        name = page["name"]
        url = page["url"]
        css_selector = page.get("css_selector")
        price_threshold_pct = page.get("price_threshold_pct")

        before = state.get(name)
        if price_threshold_pct is not None:
            interval = page.get("check_interval_minutes", DEFAULT_PRICE_CHECK_INTERVAL_MINUTES)
            results.append(_check_price_page(name, url, css_selector, price_threshold_pct, interval, state))
        else:
            results.append(_check_content_page(name, url, css_selector, state))

        after = state.get(name)
        if after is not before:
            touched[name] = after

    state_store.merge_json_state(STATE_FILE, touched)
    return results


def main():
    results = check()
    if not results:
        print("No pages configured to watch.")
    for line in results:
        print(line)


if __name__ == "__main__":
    main()
