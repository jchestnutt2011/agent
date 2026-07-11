import difflib
from pathlib import Path

import state_store

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
    return state_store.load_json_state(MEMORY_FILE)


def _closest_key(key, data):
    """Fall back to a fuzzy/substring match so recall survives the model asking
    for a slightly different key than the one it originally saved under."""
    if not data:
        return None
    substring_matches = [k for k in data if key.lower() in k.lower() or k.lower() in key.lower()]
    if len(substring_matches) == 1:
        return substring_matches[0]
    close = difflib.get_close_matches(key, data.keys(), n=1, cutoff=0.6)
    return close[0] if close else None


def run(action, key=None, value=None):
    if action == "save":
        if not key or value is None:
            return "save requires both 'key' and 'value'."
        # Locked merge, not load-mutate-save of a snapshot: the system
        # prompt tells the model to call this tool once per fact when a
        # message has several ("her name AND a preference"), and app.py
        # runs a turn's tool calls concurrently — two saves landing in the
        # same turn is an expected, not hypothetical, case. A plain
        # load-then-save here would let the second writer silently clobber
        # the first's key with a stale snapshot that never saw it.
        state_store.merge_json_state(MEMORY_FILE, {key: value})
        return f"Saved memory '{key}'."

    if action == "recall":
        if not key:
            return "recall requires 'key'."
        data = _load()
        if key in data:
            return data[key]
        fallback = _closest_key(key, data)
        if fallback:
            return f"(closest match: '{fallback}') {data[fallback]}"
        return f"No memory found for '{key}'."

    if action == "list":
        data = _load()
        if not data:
            return "No memories stored yet."
        return "\n".join(f"- {k}: {v}" for k, v in data.items())

    if action == "forget":
        if not key:
            return "forget requires 'key'."
        with state_store.file_lock(MEMORY_FILE):
            data = _load()
            if key not in data:
                return f"No memory found for '{key}'."
            del data[key]
            state_store.save_json_state(MEMORY_FILE, data)
        return f"Forgot memory '{key}'."

    return f"Unknown action: {action}"
