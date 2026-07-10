import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from tools.http_headers import BROWSER_HEADERS

ATOM_NS = "{http://www.w3.org/2005/Atom}"

# Reddit throttles unauthenticated RSS to ~1 req/min as of mid-2026. Appending
# the user/feed params from https://www.reddit.com/prefs/feeds/ (private,
# gitignored — never commit this file) bypasses that limit even for public
# subreddit feeds.
AUTH_FILE = Path(__file__).parent.parent / "reddit_auth.json"


def _load_auth():
    if not AUTH_FILE.exists():
        return {}
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not data.get("user") or not data.get("feed"):
        return {}
    return {"user": data["user"], "feed": data["feed"]}

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_reddit_top",
        "description": "Get the top posts from the last 24 hours for a given subreddit.",
        "parameters": {
            "type": "object",
            "properties": {
                "subreddit": {"type": "string", "description": "Subreddit name without 'r/', e.g. 'gaming'"},
                "limit": {"type": "integer", "description": "Number of posts to return (default 5)"},
            },
            "required": ["subreddit"],
        },
    },
}


def fetch_posts(subreddit, limit=5):
    """Returns a list of {'title', 'url'} dicts, or a string error message.
    Never raises — a network error or malformed feed comes back as an error
    string, so the chat tool and the daily briefing degrade gracefully."""
    url = f"https://www.reddit.com/r/{subreddit}/top/.rss"
    params = {"t": "day", "limit": limit, **_load_auth()}

    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=10)
        except requests.RequestException as e:
            return f"Could not fetch r/{subreddit}: {e}"
        if resp.status_code != 429:
            break
        # Don't sleep after the final attempt — we're about to give up anyway.
        if attempt < 2:
            time.sleep(15 * (attempt + 1))

    if resp.status_code != 200:
        return f"Could not fetch r/{subreddit}: HTTP {resp.status_code}"

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        return f"Could not parse r/{subreddit} feed: {e}"

    entries = root.findall(f"{ATOM_NS}entry")[:limit]
    if not entries:
        return f"No posts found for r/{subreddit}."

    posts = []
    for entry in entries:
        title = entry.findtext(f"{ATOM_NS}title", default="(no title)")
        link_el = entry.find(f"{ATOM_NS}link")
        link = link_el.get("href") if link_el is not None else ""
        posts.append({"title": title, "url": link})
    return posts


def run(subreddit, limit=5):
    posts = fetch_posts(subreddit, limit)
    if isinstance(posts, str):
        return posts
    lines = [f"- {p['title']} ({p['url']})" for p in posts]
    return f"Top posts in r/{subreddit} (past 24h):\n" + "\n".join(lines)
