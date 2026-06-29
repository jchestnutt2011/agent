from datetime import datetime, timedelta, timezone

from ddgs import DDGS

MAX_AGE_DAYS = 14

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
        try:
            published = datetime.fromisoformat(r["date"])
        except (KeyError, ValueError):
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
