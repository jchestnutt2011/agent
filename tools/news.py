import re
from datetime import datetime, timedelta, timezone

from ddgs import DDGS

MAX_AGE_DAYS = 14

# ddgs.news() reports dates inconsistently depending on source: sometimes a full
# ISO timestamp, sometimes a relative string like "7h", "16h", "2d", "3mo".
RELATIVE_UNITS = {
    "min": "minutes", "m": "minutes",
    "h": "hours",
    "d": "days",
    "mo": "days",  # approximate a month as 30 days, good enough for a freshness filter
    "y": "days",
}


def _parse_date(date_str):
    try:
        return datetime.fromisoformat(date_str)
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


def run(query, max_results=5):
    with DDGS() as ddgs:
        # over-fetch since stale results get filtered out below
        results = list(ddgs.news(query, max_results=max_results * 3))

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    fresh = []
    for r in results:
        date_str = r.get("date")
        if not date_str:
            continue
        published = _parse_date(date_str)
        if published is None:
            continue
        if published >= cutoff:
            fresh.append((published, r))

    fresh.sort(key=lambda pair: pair[0], reverse=True)
    fresh = fresh[:max_results]

    if not fresh:
        return f"No news from the past {MAX_AGE_DAYS} days found for '{query}'."

    lines = []
    for published, r in fresh:
        date_str = published.strftime("%Y-%m-%d")
        lines.append(f"- [{date_str}] {r['title']} ({r['source']}): {r['body']}")
    return "\n".join(lines)
