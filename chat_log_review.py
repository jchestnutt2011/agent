"""On-request analysis of chat_log.jsonl (+ chat_log.jsonl.previous) — NOT
a scheduled task, not a chat tool, not something that writes or deploys
anything. Run manually whenever it's worth asking "what has this thing
actually been used for, and where does it keep falling short."

This project's meta-agent workflow (Claude reviewing real usage and
writing new tools) stays on-request and human-reviewed by design — see
tools/CONTRIBUTING.md's "a 7B local model isn't trusted to author its own
tools unsupervised, Claude always writes them" and the fact that every
tool this project has ever gotten came from an explicit ask, never an
autonomous pipeline. This script only does the read-only aggregation step
that makes reviewing chat_log.jsonl fast — the actual "does this pattern
justify a new tool" judgment, and any code that follows from it, is still
a separate, deliberate conversation, same as every other tool so far.

Usage:
    python chat_log_review.py                 # this week + last week (if rotated)
    python chat_log_review.py --current-only   # just the in-progress week
    python chat_log_review.py --telegram       # also push a short digest
"""

import argparse
import json
from collections import Counter

from tools import chat_log, telegram_notify

PREVIOUS_LOG_FILE = chat_log.LOG_FILE.parent / "chat_log.jsonl.previous"

# Keep report lines readable — a real user message is rarely this long,
# and the point here is spotting a pattern across many turns, not
# reproducing any one of them in full (chat_log.jsonl itself already has
# the untruncated original).
MAX_DISPLAY_CHARS = 150


def _short(text, limit=MAX_DISPLAY_CHARS):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "..."


def _load_entries(paths):
    """Skips missing files and corrupted lines rather than failing the
    whole review over one bad entry."""
    entries = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def summarize(entries):
    """Pure function (no I/O) — easy to test, easy to reformat for
    different output targets (console report vs. Telegram digest)."""
    tool_calls = Counter()
    tool_errors = Counter()
    error_messages = Counter()
    no_tool_turns = []
    max_iteration_turns = []

    for entry in entries:
        calls = entry.get("tool_calls") or []
        if not calls:
            no_tool_turns.append(entry.get("user_message", ""))
        for call in calls:
            tool_calls[call["name"]] += 1
            if call.get("error"):
                tool_errors[call["name"]] += 1
                error_messages[call["error"]] += 1
        if entry.get("hit_max_iterations"):
            max_iteration_turns.append(entry.get("user_message", ""))

    return {
        "total_turns": len(entries),
        "tool_calls": dict(tool_calls),
        "tool_errors": dict(tool_errors),
        "top_errors": error_messages.most_common(5),
        "no_tool_turns": no_tool_turns,
        "max_iteration_turns": max_iteration_turns,
    }


def format_report(stats):
    lines = [f"Chat log review — {stats['total_turns']} turn(s)"]
    if not stats["total_turns"]:
        lines.append("Nothing logged in this period.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Tool usage:")
    if stats["tool_calls"]:
        for name, count in sorted(stats["tool_calls"].items(), key=lambda kv: -kv[1]):
            errors = stats["tool_errors"].get(name, 0)
            error_note = f" ({errors} error{'s' if errors != 1 else ''})" if errors else ""
            lines.append(f"  - {name}: {count} call(s){error_note}")
    else:
        lines.append("  (no tool calls this period)")

    if stats["top_errors"]:
        lines.append("")
        lines.append("Most common errors:")
        for message, count in stats["top_errors"]:
            lines.append(f"  - ({count}x) {_short(message)}")

    lines.append("")
    lines.append(f"Turns with no tool call: {len(stats['no_tool_turns'])}")
    for msg in stats["no_tool_turns"][:10]:
        lines.append(f"  - {_short(msg)}")
    if len(stats["no_tool_turns"]) > 10:
        lines.append(f"  ... and {len(stats['no_tool_turns']) - 10} more")

    if stats["max_iteration_turns"]:
        lines.append("")
        lines.append(f"Turns that hit the iteration cap (likely stuck/looping): {len(stats['max_iteration_turns'])}")
        for msg in stats["max_iteration_turns"]:
            lines.append(f"  - {_short(msg)}")

    return "\n".join(lines)


def format_telegram_digest(stats):
    """Compact push-notification version — headline numbers, not the
    turn-by-turn detail format_report gives."""
    if not stats["total_turns"]:
        return "\U0001F4CB <b>Chat log review</b>\nNothing logged this period."

    lines = [f"\U0001F4CB <b>Chat log review</b> — {stats['total_turns']} turn(s)"]
    top_tools = sorted(stats["tool_calls"].items(), key=lambda kv: -kv[1])[:5]
    if top_tools:
        lines.append("Top tools: " + ", ".join(f"{n} ({c})" for n, c in top_tools))
    total_errors = sum(stats["tool_errors"].values())
    if total_errors:
        lines.append(f"Tool errors: {total_errors}")
    if stats["no_tool_turns"]:
        lines.append(f"No-tool turns: {len(stats['no_tool_turns'])}")
    if stats["max_iteration_turns"]:
        lines.append(f"Hit iteration cap: {len(stats['max_iteration_turns'])}")
    return "\n".join(lines)


def run(current_only=False):
    paths = [chat_log.LOG_FILE] if current_only else [chat_log.LOG_FILE, PREVIOUS_LOG_FILE]
    return summarize(_load_entries(paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--current-only", action="store_true", help="Skip chat_log.jsonl.previous, just the in-progress week.")
    parser.add_argument("--telegram", action="store_true", help="Also push a short digest to Telegram.")
    args = parser.parse_args()

    stats = run(current_only=args.current_only)
    print(format_report(stats))

    if args.telegram:
        sent = telegram_notify.send_message(format_telegram_digest(stats))
        print()
        print("Telegram digest sent." if sent else "Telegram digest not sent (not configured or failed).")


if __name__ == "__main__":
    main()
