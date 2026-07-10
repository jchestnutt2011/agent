import difflib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from ddgs import DDGS

from tools.http_headers import BROWSER_HEADERS

MAX_AGE_DAYS = 14

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

# ddgs.news() reports dates inconsistently depending on source: sometimes a full
# ISO timestamp, sometimes a relative string like "7h", "16h", "2d", "3mo".
RELATIVE_UNITS = {
    "min": "minutes", "m": "minutes",
    "h": "hours",
    "d": "days",
    "mo": "days",  # approximate a month as 30 days, good enough for a freshness filter
    "y": "days",
}


def _as_utc(dt):
    """Force a datetime to timezone-aware UTC. Both source paths below can
    yield NAIVE datetimes — ddgs sometimes returns a bare ISO string with no
    offset, and RFC 822 pubDates with a '-0000' zone (which Google News does
    emit) parse to naive — and fetch_headlines compares these against a
    tz-aware cutoff. Mixing naive and aware raises TypeError, which silently
    took down the whole news fetch. Treat a missing offset as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_date(date_str):
    try:
        return _as_utc(datetime.fromisoformat(date_str))
    except ValueError:
        pass

    match = re.fullmatch(r"(\d+)\s*(min|mo|[mhdy])", date_str.strip())
    if not match:
        return None
    amount, unit = match.groups()
    amount = int(amount)
    if unit == "mo":
        amount *= 30
    elif unit == "y":
        amount *= 365
    kwarg = RELATIVE_UNITS[unit]
    return datetime.now(timezone.utc) - timedelta(**{kwarg: amount})


def _parse_pubdate(date_str):
    """Google News RSS uses standard RFC 822 pubDate strings."""
    try:
        return _as_utc(parsedate_to_datetime(date_str))
    except (TypeError, ValueError):
        return None


SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_news",
        "description": "Get recent news headlines for a topic or location.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic or location to search news for, e.g. 'Durham NC' or 'world news'"},
                "max_results": {"type": "integer", "description": "Number of headlines to return (default 5)"},
            },
            "required": ["query"],
        },
    },
}


def _fetch_ddgs(query, max_results):
    """ddgs scrapes DuckDuckGo's search backend (unofficial, occasionally
    flaky) but is the only source of real snippet/body text and images."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
    except Exception:
        return []

    items = []
    for r in results:
        date_str = r.get("date")
        published = _parse_date(date_str) if date_str else None
        if published is None:
            continue
        items.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "source": r.get("source", ""),
            "published": published,
            "body": r.get("body", ""),
            "image": r.get("image"),
        })
    return items


def _fetch_google_news(query, max_results):
    """Google News RSS: no API key, structured, official-ish, far more
    stable than scraped search results. No real snippet text (description
    is just a decorative HTML duplicate of the title) and no images, so
    ddgs remains the source for those — this is mainly for coverage/reliability."""
    try:
        resp = requests.get(
            GOOGLE_NEWS_RSS,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers=BROWSER_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError):
        return []

    items = []
    for item in root.findall("./channel/item")[: max_results * 2]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = item.findtext("pubDate")
        published = _parse_pubdate(pub_date) if pub_date else None
        if not title or not link or published is None:
            continue

        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        # Google appends " - {source}" to the title; drop the duplicate since
        # source is already tracked as its own field.
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()

        items.append({
            "title": title,
            "url": link,
            "source": source,
            "published": published,
            "body": "",
            "image": None,
        })
    return items[:max_results]


def _dedupe(items):
    """Merge near-duplicate stories covered by multiple sources (same event,
    different phrasing). Keeps the first-seen version but adopts a later
    duplicate's body text if the kept one doesn't have any."""
    kept = []
    for item in items:
        match_idx = next(
            (i for i, k in enumerate(kept)
             if difflib.SequenceMatcher(None, item["title"].lower(), k["title"].lower()).ratio() > 0.75),
            None,
        )
        if match_idx is None:
            kept.append(item)
        elif not kept[match_idx]["body"] and item["body"]:
            kept[match_idx] = {**kept[match_idx], "body": item["body"], "image": kept[match_idx]["image"] or item["image"]}
    return kept


def fetch_headlines(query, max_results=5):
    """Structured, deduped, freshness-filtered headlines merged from Google
    News RSS and ddgs. Returns a list of dicts: title, url, source,
    published (datetime), body, image — newest first."""
    # Over-fetch from each source since freshness filtering and dedup both
    # remove candidates before the final max_results cut.
    combined = _fetch_google_news(query, max_results * 2) + _fetch_ddgs(query, max_results * 2)

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    fresh = [item for item in combined if item["published"] >= cutoff]
    fresh.sort(key=lambda item: item["published"], reverse=True)

    return _dedupe(fresh)[:max_results]


def run(query, max_results=5):
    headlines = fetch_headlines(query, max_results)
    if not headlines:
        return f"No news from the past {MAX_AGE_DAYS} days found for '{query}'."

    lines = []
    for item in headlines:
        date_str = item["published"].strftime("%Y-%m-%d")
        source = f" ({item['source']})" if item["source"] else ""
        body = f": {item['body']}" if item["body"] else ""
        lines.append(f"- [{date_str}] {item['title']}{source}{body} — {item['url']}")
    return "\n".join(lines)
