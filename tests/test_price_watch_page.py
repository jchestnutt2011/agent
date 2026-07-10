import json

from streamlit.testing.v1 import AppTest

import page_watcher


def _isolate_files(tmp_path, monkeypatch):
    config_file = tmp_path / "page_watch_config.json"
    state_file = tmp_path / "page_watch_state.json"
    config_file.write_text(json.dumps({"pages": []}), encoding="utf-8")
    monkeypatch.setattr(page_watcher, "CONFIG_FILE", config_file)
    monkeypatch.setattr(page_watcher, "STATE_FILE", state_file)
    return config_file, state_file


def test_page_loads_with_no_watches(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)
    at = AppTest.from_file("pages/2_Price_Watch.py")
    at.run()
    assert at.exception == []
    assert any("No price watches yet" in c.value for c in at.caption)


def test_add_price_watch_success_flow(tmp_path, monkeypatch):
    config_file, state_file = _isolate_files(tmp_path, monkeypatch)
    monkeypatch.setattr(
        page_watcher, "_check_price_page",
        lambda name, url, css, threshold, interval, state: (
            state.__setitem__(name, {"reference_price": 30.0, "last_price": 30.0, "last_checked_at": "now"}),
            f"{name}: baseline captured ($30.00), nothing to compare yet",
        )[1],
    )

    at = AppTest.from_file("pages/2_Price_Watch.py")
    at.run()
    inputs = at.text_input
    inputs[0].set_value("Test Product")
    inputs[1].set_value("https://example.com/product")
    at.button[-1].click()  # form submit button is the only button before any watches exist
    at.run()

    assert at.exception == []
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert config["pages"][0]["name"] == "Test Product"
    assert config["pages"][0]["price_threshold_pct"] == 10.0
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["Test Product"]["reference_price"] == 30.0


def test_add_price_watch_shows_error_on_failure(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)
    monkeypatch.setattr(
        page_watcher, "_check_price_page",
        lambda name, url, css, threshold, interval, state: f"{name}: could not check (no price found on page)",
    )

    at = AppTest.from_file("pages/2_Price_Watch.py")
    at.run()
    inputs = at.text_input
    inputs[0].set_value("Test Product")
    inputs[1].set_value("https://example.com/product")
    at.button[-1].click()
    at.run()

    assert at.exception == []
    assert any("Couldn't add this page" in e.value for e in at.error)


def test_existing_watch_renders_and_can_be_removed(tmp_path, monkeypatch):
    config_file, state_file = _isolate_files(tmp_path, monkeypatch)
    config_file.write_text(json.dumps({"pages": [
        {"name": "Test Product", "url": "https://example.com/product", "price_threshold_pct": 10, "check_interval_minutes": 240}
    ]}), encoding="utf-8")
    state_file.write_text(json.dumps({
        "Test Product": {"reference_price": 30.0, "last_price": 27.0, "last_checked_at": "2026-01-01T00:00:00+00:00"}
    }), encoding="utf-8")

    at = AppTest.from_file("pages/2_Price_Watch.py")
    at.run()
    assert at.exception == []
    assert any("Test Product" in m.value for m in at.markdown)

    remove_button = next(b for b in at.button if b.key == "remove_Test Product")
    remove_button.click()
    at.run()

    assert at.exception == []
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert config["pages"] == []
