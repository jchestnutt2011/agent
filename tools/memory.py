import json
from pathlib import Path

MEMORY_FILE = Path(__file__).parent.parent / "agent_memory.json"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "memory",
        "description": (
            "Save, recall, list, or forget persistent notes that survive across "
            "conversations. Use this to remember facts about the user, ongoing "
            "tasks, or anything worth keeping for next time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["save", "recall", "list", "forget"],
                    "description": "What to do with memory.",
                },
                "key": {
                    "type": "string",
                    "description": "Short label for the memory, e.g. 'wifi_password'. Required for save/recall/forget.",
                },
                "value": {
                    "type": "string",
                    "description": "The content to remember. Required for save.",
                },
            },
            "required": ["action"],
        },
    },
}


def _load():
    if not MEMORY_FILE.exists():
        return {}
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(data):
    MEMORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run(action, key=None, value=None):
    data = _load()

    if action == "save":
        if not key or value is None:
            return "save requires both 'key' and 'value'."
        data[key] = value
        _save(data)
        return f"Saved memory '{key}'."

    if action == "recall":
        if not key:
            return "recall requires 'key'."
        if key not in data:
            return f"No memory found for '{key}'."
        return data[key]

    if action == "list":
        if not data:
            return "No memories stored yet."
        return "\n".join(f"- {k}: {v}" for k, v in data.items())

    if action == "forget":
        if not key:
            return "forget requires 'key'."
        if key in data:
            del data[key]
            _save(data)
            return f"Forgot memory '{key}'."
        return f"No memory found for '{key}'."

    return f"Unknown action: {action}"
