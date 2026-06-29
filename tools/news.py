from ddgs import DDGS

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
        results = list(ddgs.news(query, max_results=max_results))
    if not results:
        return f"No news found for '{query}'."

    lines = []
    for r in results:
        lines.append(f"- {r['title']} ({r['source']}): {r['body']}")
    return "\n".join(lines)
