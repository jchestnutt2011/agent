import json

import state_store


def test_load_json_state_missing_file_returns_empty_dict(tmp_path):
    assert state_store.load_json_state(tmp_path / "nope.json") == {}


def test_load_json_state_malformed_json_returns_empty_dict(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")
    assert state_store.load_json_state(path) == {}


def test_load_json_state_reads_existing_data(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert state_store.load_json_state(path) == {"a": 1}


def test_save_json_state_roundtrips(tmp_path):
    path = tmp_path / "state.json"
    state_store.save_json_state(path, {"x": "y"})
    assert state_store.load_json_state(path) == {"x": "y"}


def test_save_json_state_writes_atomically_no_leftover_tmp_file(tmp_path):
    path = tmp_path / "state.json"
    state_store.save_json_state(path, {"a": 1})
    assert not path.with_suffix(".tmp").exists()
    assert path.exists()
