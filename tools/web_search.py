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
    # ddgs scrapes DuckDuckGo (unofficial) and does rate-limit / go flaky.
    # This is also the fallback the system prompt tells the model to reach
    # for when other tools fail, so it must degrade to a string the model
    # can act on, never raise. Use .get() for fields too, since result shape
    # isn't guaranteed.
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
    except Exception as e:
        return f"Web search failed: {e}. Try rephrasing the query or again shortly."

    if not results:
        return "No results found."

    lines = []
    for r in results:
        title = r.get("title", "(no title)")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"- {title}: {body} ({href})")
    return "\n".join(lines)
