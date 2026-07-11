import json

import chat_log_review as review
from tools import chat_log


def _entry(user_message="hi", tool_calls=None, hit_max_iterations=False):
    return {
        "timestamp": "2026-07-10T00:00:00+00:00",
        "user_message": user_message,
        "tool_calls": tool_calls or [],
        "final_response": "ok",
        "iterations": 1,
        "elapsed_seconds": 0.5,
        "hit_max_iterations": hit_max_iterations,
    }


def _call(name, error=None):
    return {"name": name, "args": {}, "result": None if error else "ok", "error": error}


def test_load_entries_skips_missing_files(tmp_path):
    entries = review._load_entries([tmp_path / "nope.jsonl"])
    assert entries == []


def test_load_entries_skips_corrupted_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"user_message": "good"}\nnot json\n{"user_message": "also good"}\n', encoding="utf-8")
    entries = review._load_entries([path])
    assert len(entries) == 2


def test_summarize_empty():
    stats = review.summarize([])
    assert stats["total_turns"] == 0
    assert stats["tool_calls"] == {}
    assert stats["no_tool_turns"] == []


def test_summarize_counts_tool_calls_and_errors():
    entries = [
        _entry(tool_calls=[_call("get_weather"), _call("get_news")]),
        _entry(tool_calls=[_call("get_weather"), _call("get_weather", error="timeout")]),
    ]
    stats = review.summarize(entries)
    assert stats["tool_calls"] == {"get_weather": 3, "get_news": 1}
    assert stats["tool_errors"] == {"get_weather": 1}
    assert stats["top_errors"] == [("timeout", 1)]


def test_summarize_tracks_no_tool_turns():
    entries = [_entry(user_message="just chatting"), _entry(tool_calls=[_call("get_weather")])]
    stats = review.summarize(entries)
    assert stats["no_tool_turns"] == ["just chatting"]


def test_summarize_tracks_max_iteration_turns():
    entries = [_entry(user_message="looped forever", hit_max_iterations=True)]
    stats = review.summarize(entries)
    assert stats["max_iteration_turns"] == ["looped forever"]


def test_format_report_empty_period():
    report = review.format_report(review.summarize([]))
    assert "Nothing logged" in report


def test_format_report_includes_tool_counts_and_errors():
    stats = review.summarize([
        _entry(tool_calls=[_call("get_weather"), _call("get_weather", error="boom")]),
    ])
    report = review.format_report(stats)
    assert "get_weather: 2 call(s) (1 error)" in report
    assert "boom" in report


def test_format_report_truncates_long_messages():
    long_message = "x" * 300
    stats = review.summarize([_entry(user_message=long_message)])
    report = review.format_report(stats)
    assert long_message not in report  # full text shouldn't appear
    assert "x" * 150 + "..." in report


def test_format_telegram_digest_empty_period():
    digest = review.format_telegram_digest(review.summarize([]))
    assert "Nothing logged" in digest


def test_format_telegram_digest_includes_headline_numbers():
    stats = review.summarize([
        _entry(tool_calls=[_call("get_weather", error="boom")]),
        _entry(user_message="no tool used here"),
        _entry(hit_max_iterations=True),
    ])
    digest = review.format_telegram_digest(stats)
    assert "Top tools: get_weather (1)" in digest
    assert "Tool errors: 1" in digest
    assert "No-tool turns: 2" in digest  # the max-iteration entry also had no tool_calls
    assert "Hit iteration cap: 1" in digest


def test_run_current_only_skips_previous_file(tmp_path, monkeypatch):
    current = tmp_path / "chat_log.jsonl"
    previous = tmp_path / "chat_log.jsonl.previous"
    monkeypatch.setattr(chat_log, "LOG_FILE", current)
    monkeypatch.setattr(review, "PREVIOUS_LOG_FILE", previous)

    current.write_text(json.dumps(_entry(user_message="this week")) + "\n", encoding="utf-8")
    previous.write_text(json.dumps(_entry(user_message="last week")) + "\n", encoding="utf-8")

    stats = review.run(current_only=True)
    assert stats["total_turns"] == 1
    assert stats["no_tool_turns"] == ["this week"]


def test_run_includes_previous_by_default(tmp_path, monkeypatch):
    current = tmp_path / "chat_log.jsonl"
    previous = tmp_path / "chat_log.jsonl.previous"
    monkeypatch.setattr(chat_log, "LOG_FILE", current)
    monkeypatch.setattr(review, "PREVIOUS_LOG_FILE", previous)

    current.write_text(json.dumps(_entry(user_message="this week")) + "\n", encoding="utf-8")
    previous.write_text(json.dumps(_entry(user_message="last week")) + "\n", encoding="utf-8")

    stats = review.run(current_only=False)
    assert stats["total_turns"] == 2
