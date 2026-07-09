from tools import memory


def test_save_and_recall_exact_key(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "agent_memory.json")
    memory.run("save", key="favorite_pizza_place", value="Pie Pushers")
    assert memory.run("recall", key="favorite_pizza_place") == "Pie Pushers"


def test_save_writes_atomically_no_tmp_file_left_behind(tmp_path, monkeypatch):
    mem_file = tmp_path / "agent_memory.json"
    monkeypatch.setattr(memory, "MEMORY_FILE", mem_file)
    memory.run("save", key="k", value="v")
    assert mem_file.exists()
    assert not mem_file.with_suffix(".tmp").exists()


def test_recall_falls_back_to_closest_key(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "agent_memory.json")
    memory.run("save", key="favorite_pizza_place", value="Pie Pushers")
    result = memory.run("recall", key="favorite_pizza")
    assert "Pie Pushers" in result
    assert "favorite_pizza_place" in result


def test_recall_missing_key_no_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "agent_memory.json")
    memory.run("save", key="favorite_pizza_place", value="Pie Pushers")
    assert memory.run("recall", key="completely_unrelated_topic") == "No memory found for 'completely_unrelated_topic'."


def test_forget_removes_key(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "agent_memory.json")
    memory.run("save", key="k", value="v")
    memory.run("forget", key="k")
    assert memory.run("recall", key="k") == "No memory found for 'k'."
