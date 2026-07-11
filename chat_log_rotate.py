"""Runs weekly via Windows Task Scheduler. Rotates chat_log.jsonl so it
never grows unbounded — the point of that file (reviewing real usage later
to spot patterns worth building a tool for) doesn't need infinite history,
just enough to look back over comfortably.

Rotation, not deletion: the just-finished week's log is kept as
chat_log.jsonl.previous (overwritten each time, so exactly one prior week
is ever kept) rather than discarded outright — a straight wipe would leave
zero history available between the moment rotation runs and the moment
enough of a new week has accumulated to be worth reviewing again.
"""

from tools import chat_log

PREVIOUS_LOG_FILE = chat_log.LOG_FILE.parent / "chat_log.jsonl.previous"


def rotate():
    """Returns a human-readable result line (also the log output when run
    via the scheduled task). Never raises — a rotation failure shouldn't
    take down the task, just leave the log to grow until the next attempt."""
    if not chat_log.LOG_FILE.exists():
        return "No chat_log.jsonl to rotate — nothing logged this week."

    try:
        with chat_log.LOG_FILE.open(encoding="utf-8") as f:
            line_count = sum(1 for _ in f)
        chat_log.LOG_FILE.replace(PREVIOUS_LOG_FILE)
    except OSError as e:
        return f"Could not rotate chat_log.jsonl: {e}"

    return f"Rotated chat_log.jsonl ({line_count} entries) to chat_log.jsonl.previous."


def main():
    print(rotate())


if __name__ == "__main__":
    main()
