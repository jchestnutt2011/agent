import json
import time

import pytest

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


def test_file_lock_excludes_a_second_acquire(tmp_path):
    path = tmp_path / "state.json"
    with state_store.file_lock(path, timeout=1):
        with pytest.raises(TimeoutError):
            with state_store.file_lock(path, timeout=0.2):
                pass  # should never get here — lock is already held


def test_file_lock_releases_on_exit(tmp_path):
    path = tmp_path / "state.json"
    with state_store.file_lock(path):
        pass
    # A second acquire right after must succeed immediately, not time out.
    with state_store.file_lock(path, timeout=1):
        pass


def test_file_lock_cleans_up_stale_lock_from_a_dead_process(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.write_text("", encoding="utf-8")
    # Backdate the lock file's mtime past the staleness threshold.
    stale_time = time.time() - state_store.STALE_LOCK_SECONDS - 1
    import os
    os.utime(lock_path, (stale_time, stale_time))

    # Must acquire despite the "held" lock, since it's older than the
    # staleness threshold — a crashed process's lock can't wedge this forever.
    with state_store.file_lock(path, timeout=1):
        pass


def test_file_lock_retries_on_permission_error_not_just_file_exists_error(tmp_path, monkeypatch):
    """Windows can raise PermissionError (WinError 5) instead of
    FileExistsError from os.open(O_CREAT|O_EXCL) when another thread is
    concurrently unlinking/recreating the exact same lock filename — an
    NTFS delete-pending race. Reproduced for real under a 20-thread stress
    test on tools/memory.py's locked saves (state_store.py:61). This
    deterministically forces that path instead of relying on timing."""
    import os as os_module
    path = tmp_path / "state.json"
    real_open = os_module.open
    calls = []

    def flaky_open(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("simulated WinError 5 delete-pending race")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(state_store.os, "open", flaky_open)

    with state_store.file_lock(path, timeout=1):
        pass  # must not raise — the PermissionError must be retried, not propagated

    assert len(calls) >= 2


def test_merge_json_state_merges_onto_current_disk_contents_not_caller_snapshot(tmp_path):
    """The exact race this exists to prevent: caller A loads state, caller B
    (e.g. the Streamlit UI) writes a change to an untouched key, then caller
    A finishes and merges its own update. B's write must survive."""
    path = tmp_path / "state.json"
    state_store.save_json_state(path, {"page_one": {"v": 1}})

    # Caller A's stale in-memory view, taken before B's write below.
    a_snapshot_before_b_wrote = state_store.load_json_state(path)
    assert "page_two" not in a_snapshot_before_b_wrote

    # Caller B writes a new key directly (simulating the Streamlit UI).
    state_store.save_json_state(path, {**a_snapshot_before_b_wrote, "page_two": {"v": 2}})

    # Caller A now merges only what it touched (page_one), unaware of page_two.
    state_store.merge_json_state(path, {"page_one": {"v": 99}})

    final = state_store.load_json_state(path)
    assert final["page_one"] == {"v": 99}
    assert final["page_two"] == {"v": 2}  # not clobbered


def test_merge_json_state_no_op_on_empty_updates(tmp_path):
    path = tmp_path / "state.json"
    state_store.save_json_state(path, {"a": 1})
    state_store.merge_json_state(path, {})
    assert state_store.load_json_state(path) == {"a": 1}
