import time

import pytest

import app
from tools import chat_log


@pytest.fixture(autouse=True)
def _isolate_chat_log(tmp_path, monkeypatch):
    """Every test in this file drives app.run_turn(), which now logs each
    turn — point it at a scratch file so tests never touch the real log."""
    monkeypatch.setattr(chat_log, "LOG_FILE", tmp_path / "chat_log.jsonl")


def test_execute_tool_dispatches_with_args(monkeypatch):
    monkeypatch.setitem(app.dispatch, "echo", lambda text: f"echoed: {text}")
    call = {"function": {"name": "echo", "arguments": {"text": "hi"}}}
    result = app._execute_tool(call)
    assert result == {"name": "echo", "args": {"text": "hi"}, "content": "echoed: hi", "error": None}


def test_execute_tool_unknown_tool_returns_message():
    call = {"function": {"name": "not_a_real_tool", "arguments": {}}}
    result = app._execute_tool(call)
    assert result["content"] == "Unknown tool: not_a_real_tool"
    assert result["error"] == "Unknown tool: not_a_real_tool"


def test_execute_tool_catches_exceptions(monkeypatch):
    def raise_error(**kwargs):
        raise ValueError("boom")
    monkeypatch.setitem(app.dispatch, "broken", raise_error)
    call = {"function": {"name": "broken", "arguments": {}}}
    result = app._execute_tool(call)
    assert "broken" in result["content"]
    assert "boom" in result["content"]
    assert result["error"] == result["content"]


def test_run_turn_preserves_tool_call_order_despite_out_of_order_completion(monkeypatch):
    """The core regression test for concurrent execution: Ollama matches
    each appended tool message back to its tool_call by position in the
    message list, not by an explicit id. If the slower call is listed
    FIRST but finishes LAST, its result must still be appended first."""

    def slow_tool():
        time.sleep(0.2)
        return "SLOW_RESULT"

    def fast_tool():
        return "FAST_RESULT"

    monkeypatch.setitem(app.dispatch, "slow_tool", slow_tool)
    monkeypatch.setitem(app.dispatch, "fast_tool", fast_tool)

    call_count = []

    def fake_chat(model, messages, tools, keep_alive, options):
        call_count.append(1)
        if len(call_count) == 1:
            return {
                "message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [
                        {"function": {"name": "slow_tool", "arguments": {}}},
                        {"function": {"name": "fast_tool", "arguments": {}}},
                    ],
                }
            }
        return {"message": {"role": "assistant", "content": "done"}}

    monkeypatch.setattr(app.ollama, "chat", fake_chat)

    messages = [{"role": "user", "content": "do both things"}]
    result = app.run_turn(messages)

    assert result == "done"
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert [m["content"] for m in tool_messages] == ["SLOW_RESULT", "FAST_RESULT"]


def test_run_turn_single_tool_call(monkeypatch):
    monkeypatch.setitem(app.dispatch, "get_thing", lambda: "THE_THING")

    call_count = []

    def fake_chat(model, messages, tools, keep_alive, options):
        call_count.append(1)
        if len(call_count) == 1:
            return {
                "message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [{"function": {"name": "get_thing", "arguments": {}}}],
                }
            }
        return {"message": {"role": "assistant", "content": "here it is"}}

    monkeypatch.setattr(app.ollama, "chat", fake_chat)

    messages = [{"role": "user", "content": "get the thing"}]
    result = app.run_turn(messages)

    assert result == "here it is"
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert tool_messages == [{"role": "tool", "content": "THE_THING"}]


def test_run_turn_no_tool_calls_returns_content_directly(monkeypatch):
    monkeypatch.setattr(
        app.ollama, "chat",
        lambda model, messages, tools, keep_alive, options: {"message": {"role": "assistant", "content": "just an answer"}},
    )
    result = app.run_turn([{"role": "user", "content": "hi"}])
    assert result == "just an answer"


def test_run_turn_gives_up_after_max_iterations(monkeypatch):
    monkeypatch.setitem(app.dispatch, "loop_tool", lambda: "again")
    monkeypatch.setattr(
        app.ollama, "chat",
        lambda model, messages, tools, keep_alive, options: {
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": "loop_tool", "arguments": {}}}],
            }
        },
    )
    result = app.run_turn([{"role": "user", "content": "loop forever"}])
    assert "wasn't able to finish" in result


# --- Logging integration ---

def test_run_turn_logs_a_no_tool_turn(monkeypatch):
    monkeypatch.setattr(
        app.ollama, "chat",
        lambda model, messages, tools, keep_alive, options: {"message": {"role": "assistant", "content": "just an answer"}},
    )
    app.run_turn([{"role": "user", "content": "hi there"}])

    lines = chat_log.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json
    entry = json.loads(lines[0])
    assert entry["user_message"] == "hi there"
    assert entry["final_response"] == "just an answer"
    assert entry["tool_calls"] == []
    assert entry["iterations"] == 1
    assert entry["hit_max_iterations"] is False


def test_run_turn_logs_tool_calls_with_results_and_errors(monkeypatch):
    monkeypatch.setitem(app.dispatch, "good_tool", lambda: "GOOD_RESULT")

    def bad_tool():
        raise ValueError("bad thing")
    monkeypatch.setitem(app.dispatch, "bad_tool", bad_tool)

    call_count = []

    def fake_chat(model, messages, tools, keep_alive, options):
        call_count.append(1)
        if len(call_count) == 1:
            return {
                "message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [
                        {"function": {"name": "good_tool", "arguments": {}}},
                        {"function": {"name": "bad_tool", "arguments": {}}},
                    ],
                }
            }
        return {"message": {"role": "assistant", "content": "final"}}

    monkeypatch.setattr(app.ollama, "chat", fake_chat)
    app.run_turn([{"role": "user", "content": "run both"}])

    import json
    entry = json.loads(chat_log.LOG_FILE.read_text(encoding="utf-8").strip())
    assert len(entry["tool_calls"]) == 2
    good, bad = entry["tool_calls"]
    assert good["name"] == "good_tool" and good["result"] == "GOOD_RESULT" and good["error"] is None
    assert bad["name"] == "bad_tool" and bad["result"] is None and "bad thing" in bad["error"]


def test_run_turn_logs_hit_max_iterations(monkeypatch):
    monkeypatch.setitem(app.dispatch, "loop_tool", lambda: "again")
    monkeypatch.setattr(
        app.ollama, "chat",
        lambda model, messages, tools, keep_alive, options: {
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": "loop_tool", "arguments": {}}}],
            }
        },
    )
    app.run_turn([{"role": "user", "content": "loop forever"}])

    import json
    entry = json.loads(chat_log.LOG_FILE.read_text(encoding="utf-8").strip())
    assert entry["hit_max_iterations"] is True
    assert entry["iterations"] == app.MAX_TOOL_ITERATIONS
    assert len(entry["tool_calls"]) == app.MAX_TOOL_ITERATIONS  # one per iteration
