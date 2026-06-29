import time
import xml.etree.ElementTree as ET

import requests

ATOM_NS = "{http://www.w3.org/2005/Atom}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

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
    """Returns a list of {'title', 'url'} dicts, or a string error message."""
    url = f"https://www.reddit.com/r/{subreddit}/top/.rss"

    resp = None
    for attempt in range(5):
        resp = requests.get(url, params={"t": "day", "limit": limit}, headers=HEADERS, timeout=10)
        if resp.status_code != 429:
            break
        time.sleep(15 * (attempt + 1))

    if resp.status_code != 200:
        return f"Could not fetch r/{subreddit}: HTTP {resp.status_code}"

    root = ET.fromstring(resp.content)
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
