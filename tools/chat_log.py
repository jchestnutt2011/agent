"""Structured JSONL log of every chat turn — user message, tool calls made
(with args, results, and errors kept distinct), final answer, and timing.
Not a chat tool (no SCHEMA/run); imported directly by app.py, same shape as
tools/telegram_notify.py.

The point: every tool in this project so far came from a direct request or
independent research, never from actually looking at how the thing gets
used. This log exists so that can change — reviewing it later (by a human
or by Claude) can surface real patterns: a tool that gets reached for
constantly, a request that repeatedly dead-ends with no good tool to call,
a query the model keeps answering from its own (possibly wrong) knowledge
because nothing structured exists for it.

Gitignored, deliberately: this captures real conversations verbatim,
including anything ever typed into chat — this project has already had a
live API key pasted directly into a message once. Never commit this file,
and don't assume it's safe to share as-is; skim before forwarding it
anywhere.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path(__file__).parent.parent / "chat_log.jsonl"

# Keep individual entries bounded — some tool results (web_search, news,
# esports schedules) can run several KB, and the point of this log is
# spotting patterns, not archiving full output verbatim.
MAX_RESULT_CHARS = 1500
MAX_RESPONSE_CHARS = 4000


def _truncate(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated, {len(text)} chars total]"


def log_turn(user_message, tool_calls, final_response, iterations, elapsed_seconds, hit_max_iterations=False):
    """Appends one JSON object (one line) to LOG_FILE. tool_calls is a list
    of {"name", "args", "content", "error"} dicts (error is None on
    success). Never raises — a logging failure must not break the chat
    turn it's trying to record."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_message": user_message,
        "tool_calls": [
            {
                "name": call["name"],
                "args": call["args"],
                "result": _truncate(call["content"], MAX_RESULT_CHARS) if call.get("error") is None else None,
                "error": call.get("error"),
            }
            for call in tool_calls
        ],
        "final_response": _truncate(final_response, MAX_RESPONSE_CHARS),
        "iterations": iterations,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "hit_max_iterations": hit_max_iterations,
    }
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
