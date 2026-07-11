import json

from tools import chat_log


def _tool_call(name="get_weather", args=None, content="sunny", error=None):
    return {"name": name, "args": args or {}, "content": content, "error": error}


def test_log_turn_writes_one_json_line(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_log, "LOG_FILE", tmp_path / "chat_log.jsonl")
    chat_log.log_turn("hi", [], "hello there", 1, 0.5)

    lines = chat_log.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["user_message"] == "hi"
    assert entry["final_response"] == "hello there"
    assert entry["tool_calls"] == []
    assert entry["iterations"] == 1
    assert entry["elapsed_seconds"] == 0.5
    assert entry["hit_max_iterations"] is False
    assert "timestamp" in entry


def test_log_turn_appends_across_multiple_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_log, "LOG_FILE", tmp_path / "chat_log.jsonl")
    chat_log.log_turn("first", [], "reply one", 1, 0.1)
    chat_log.log_turn("second", [], "reply two", 1, 0.1)

    lines = chat_log.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["user_message"] == "first"
    assert json.loads(lines[1])["user_message"] == "second"


def test_log_turn_records_successful_tool_call(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_log, "LOG_FILE", tmp_path / "chat_log.jsonl")
    chat_log.log_turn("weather?", [_tool_call(content="72F and sunny")], "It's 72F and sunny.", 2, 1.2)

    entry = json.loads(chat_log.LOG_FILE.read_text(encoding="utf-8").strip())
    call = entry["tool_calls"][0]
    assert call["name"] == "get_weather"
    assert call["result"] == "72F and sunny"
    assert call["error"] is None


def test_log_turn_records_failed_tool_call_without_a_result(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_log, "LOG_FILE", tmp_path / "chat_log.jsonl")
    chat_log.log_turn(
        "weather?",
        [_tool_call(content="Tool get_weather failed: timeout", error="Tool get_weather failed: timeout")],
        "Sorry, couldn't get that.", 1, 5.0,
    )

    entry = json.loads(chat_log.LOG_FILE.read_text(encoding="utf-8").strip())
    call = entry["tool_calls"][0]
    assert call["result"] is None
    assert "timeout" in call["error"]


def test_log_turn_truncates_long_results():
    long_text = "x" * 5000
    truncated = chat_log._truncate(long_text, limit=100)
    assert len(truncated) < len(long_text)
    assert truncated.startswith("x" * 100)
    assert "truncated" in truncated
    assert "5000" in truncated


def test_log_turn_does_not_truncate_short_text():
    assert chat_log._truncate("short", limit=100) == "short"


def test_log_turn_never_raises_on_write_failure(tmp_path, monkeypatch):
    # Point at a path whose parent directory doesn't exist — open() will
    # raise FileNotFoundError (an OSError subclass), which must be swallowed.
    monkeypatch.setattr(chat_log, "LOG_FILE", tmp_path / "nonexistent_dir" / "chat_log.jsonl")
    chat_log.log_turn("hi", [], "reply", 1, 0.1)  # must not raise
