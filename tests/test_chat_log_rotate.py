import chat_log_rotate
from tools import chat_log


def test_rotate_no_log_file_returns_message(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_log, "LOG_FILE", tmp_path / "chat_log.jsonl")
    monkeypatch.setattr(chat_log_rotate, "PREVIOUS_LOG_FILE", tmp_path / "chat_log.jsonl.previous")

    result = chat_log_rotate.rotate()

    assert "No chat_log.jsonl to rotate" in result


def test_rotate_moves_log_to_previous(tmp_path, monkeypatch):
    log_file = tmp_path / "chat_log.jsonl"
    previous_file = tmp_path / "chat_log.jsonl.previous"
    monkeypatch.setattr(chat_log, "LOG_FILE", log_file)
    monkeypatch.setattr(chat_log_rotate, "PREVIOUS_LOG_FILE", previous_file)

    log_file.write_text('{"a": 1}\n{"a": 2}\n{"a": 3}\n', encoding="utf-8")

    result = chat_log_rotate.rotate()

    assert "3 entries" in result
    assert not log_file.exists()
    assert previous_file.read_text(encoding="utf-8") == '{"a": 1}\n{"a": 2}\n{"a": 3}\n'


def test_rotate_overwrites_existing_previous_file(tmp_path, monkeypatch):
    log_file = tmp_path / "chat_log.jsonl"
    previous_file = tmp_path / "chat_log.jsonl.previous"
    monkeypatch.setattr(chat_log, "LOG_FILE", log_file)
    monkeypatch.setattr(chat_log_rotate, "PREVIOUS_LOG_FILE", previous_file)

    previous_file.write_text('{"old": "week before last"}\n', encoding="utf-8")
    log_file.write_text('{"new": "last week"}\n', encoding="utf-8")

    chat_log_rotate.rotate()

    # Only the just-finished week survives — the older backup is replaced,
    # exactly one prior week is ever kept.
    assert previous_file.read_text(encoding="utf-8") == '{"new": "last week"}\n'


def test_rotate_leaves_next_weeks_log_starting_fresh(tmp_path, monkeypatch):
    log_file = tmp_path / "chat_log.jsonl"
    monkeypatch.setattr(chat_log, "LOG_FILE", log_file)
    monkeypatch.setattr(chat_log_rotate, "PREVIOUS_LOG_FILE", tmp_path / "chat_log.jsonl.previous")

    log_file.write_text('{"a": 1}\n', encoding="utf-8")
    chat_log_rotate.rotate()

    # A fresh turn after rotation should recreate chat_log.jsonl cleanly.
    chat_log.log_turn("hi", [], "hello", 1, 0.1)
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_rotate_never_raises_on_failure(tmp_path, monkeypatch):
    log_file = tmp_path / "chat_log.jsonl"
    log_file.write_text("data", encoding="utf-8")
    monkeypatch.setattr(chat_log, "LOG_FILE", log_file)
    # Target a previous-file path whose parent doesn't exist, forcing replace() to fail.
    monkeypatch.setattr(chat_log_rotate, "PREVIOUS_LOG_FILE", tmp_path / "nonexistent_dir" / "chat_log.jsonl.previous")

    result = chat_log_rotate.rotate()  # must not raise
    assert "Could not rotate" in result
