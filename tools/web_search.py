from ddgs import DDGS

SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information and return short result snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"]
        }
    }
}


def run(query):
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"- {r['title']}: {r['body']} ({r['href']})")
    return "\n".join(lines)
