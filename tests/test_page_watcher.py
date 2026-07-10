import json
from datetime import datetime, timedelta, timezone

import requests

import page_watcher as watcher


class _FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _page(name="Test Page", url="https://example.com/item", css_selector=None):
    return {"name": name, "url": url, "css_selector": css_selector}


def test_extract_text_strips_scripts_and_styles():
    html_content = "<html><body><script>evil()</script><style>.x{}</style><p>Hello  world</p></body></html>"
    assert watcher._extract_text(html_content) == "Hello world"


def test_extract_text_with_selector():
    html_content = '<div id="price">$19.99</div><div id="ad">Buy now!</div>'
    assert watcher._extract_text(html_content, "#price") == "$19.99"


def test_extract_text_missing_selector_returns_none():
    html_content = "<div id='price'>$19.99</div>"
    assert watcher._extract_text(html_content, "#nope") is None


def test_check_captures_baseline_without_notifying(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $10</p>"))
    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert sent_messages == []
    assert "baseline" in results[0]
    state = watcher._load_state()
    assert "Test Page" in state


def test_check_skips_unchanged_page(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")
    watcher._save_state({"Test Page": {"content_hash": watcher._content_hash("Price: $10"), "content_snippet": "Price: $10"}})

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $10</p>"))
    decide_calls = []
    monkeypatch.setattr(watcher, "_ask_model_to_decide", lambda *a: decide_calls.append(a) or (True, "x"))

    results = watcher.check()

    assert decide_calls == []
    assert "unchanged" in results[0]


def test_check_notifies_on_meaningful_change(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")
    watcher._save_state({"Test Page": {"content_hash": watcher._content_hash("Price: $10"), "content_snippet": "Price: $10"}})

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $5</p>"))
    monkeypatch.setattr(watcher, "_ask_model_to_decide", lambda name, old, new: (True, "price dropped"))
    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert len(sent_messages) == 1
    assert "price dropped" in sent_messages[0]
    state = watcher._load_state()
    assert state["Test Page"]["content_hash"] == watcher._content_hash("Price: $5")


def test_check_skips_noise_change_without_notifying(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")
    watcher._save_state({"Test Page": {"content_hash": watcher._content_hash("Price: $10 (1204 views)"), "content_snippet": "Price: $10 (1204 views)"}})

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $10 (1205 views)</p>"))
    monkeypatch.setattr(watcher, "_ask_model_to_decide", lambda name, old, new: (False, "just a view counter"))
    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert sent_messages == []
    assert "skipped" in results[0]
    # state still advances to the latest content so future diffs aren't stale
    state = watcher._load_state()
    assert state["Test Page"]["content_hash"] == watcher._content_hash("Price: $10 (1205 views)")


def test_check_does_not_persist_when_telegram_send_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")
    watcher._save_state({"Test Page": {"content_hash": watcher._content_hash("Price: $10"), "content_snippet": "Price: $10"}})

    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<p>Price: $5</p>"))
    monkeypatch.setattr(watcher, "_ask_model_to_decide", lambda name, old, new: (True, "price dropped"))
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: False)

    results = watcher.check()

    assert "will retry" in results[0]
    state = watcher._load_state()
    assert state["Test Page"]["content_hash"] == watcher._content_hash("Price: $10")  # unchanged, retry next cycle


def test_check_handles_fetch_failure_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page()]}), encoding="utf-8")

    def raise_error(url, headers, timeout):
        raise requests.ConnectionError("host unreachable")
    monkeypatch.setattr(watcher.requests, "get", raise_error)

    results = watcher.check()

    assert "could not check" in results[0]
    assert watcher._load_state() == {}


def test_ask_model_to_decide_handles_malformed_json_safely(monkeypatch):
    monkeypatch.setattr(watcher.ollama, "chat", lambda model, messages, format: {
        "message": {"content": "not valid json"}
    })
    notify, reason = watcher._ask_model_to_decide("Test Page", "old", "new")
    assert notify is False
    assert "precaution" in reason


def test_check_does_not_clobber_concurrent_write_to_untouched_page(tmp_path, monkeypatch):
    """Regression test for the page_watch_config/state race: check()'s loop
    can take a while fetching real pages, during which the Streamlit UI
    might add/update a different watched page. check() must not overwrite
    that concurrent write when it persists its own results."""
    import state_store

    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_page(name="Page One")]}), encoding="utf-8")

    def fake_get(url, headers, timeout):
        # Simulate a concurrent writer (e.g. the Streamlit UI) persisting a
        # brand-new page's entry while this fetch for Page One is "in flight".
        state_store.save_json_state(watcher.STATE_FILE, {"Page Two (added concurrently)": {"content_hash": "x"}})
        return _FakeResponse("<p>Page One content</p>")

    monkeypatch.setattr(watcher.requests, "get", fake_get)

    watcher.check()

    final_state = watcher._load_state()
    assert "Page One" in final_state  # this run's own result was saved
    assert "Page Two (added concurrently)" in final_state  # concurrent write survived


def test_no_pages_configured_returns_no_results(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": []}), encoding="utf-8")

    assert watcher.check() == []


# --- Price mode ---

AMAZON_TWISTER_HTML = """
<html><body>
<div class="a-price"><span class="a-offscreen">$99.99</span></div>
<script>var priceAmount = {"priceAmount": 999.00, "productTitle": "unrelated sponsored item"};</script>
<div class="a-section aok-hidden twister-plus-buying-options-price-data">
{"desktop_buybox_group_1":[{"displayPrice":"$30.00","priceAmount":30.00,"currencySymbol":"$"}]}
</div>
</body></html>
"""

CORE_PRICE_HTML = """
<html><body>
<div id="corePriceDisplay_desktop_feature_div">
  <span class="a-price"><span class="a-offscreen"></span></span>
  <span class="a-price"><span class="a-offscreen">$45.50</span></span>
</div>
</body></html>
"""

GENERIC_HTML = "<html><body><p>Now only $12.34 for a limited time!</p></body></html>"


def _price_page(name="Price Page", url="https://www.amazon.com/dp/TEST", threshold=10, css_selector=None, interval=None):
    page = {"name": name, "url": url, "price_threshold_pct": threshold}
    if css_selector:
        page["css_selector"] = css_selector
    if interval is not None:
        page["check_interval_minutes"] = interval
    return page


def test_extract_price_prefers_twister_buybox_json_over_other_prices_on_page():
    """Amazon pages embed priceAmount fields for sponsored/related products
    too — a naive first-match grab would pick up the wrong item's price."""
    assert watcher._extract_price(AMAZON_TWISTER_HTML) == 30.00


def test_extract_price_falls_back_to_core_price_offscreen():
    assert watcher._extract_price(CORE_PRICE_HTML) == 45.50


def test_extract_price_generic_fallback_for_non_amazon_page():
    assert watcher._extract_price(GENERIC_HTML) == 12.34


def test_extract_price_with_css_selector():
    html_content = '<div id="price">$19.99</div><div id="ad">Buy now for $999!</div>'
    assert watcher._extract_price(html_content, "#price") == 19.99


def test_extract_price_returns_none_when_nothing_found():
    assert watcher._extract_price("<html><body><p>no price here</p></body></html>") is None


def test_looks_blocked_detects_amazon_captcha_page():
    blocked_html = "To discuss automated access to Amazon data please contact api-services-support@amazon.com."
    assert watcher._looks_blocked(blocked_html) is True
    assert watcher._looks_blocked(AMAZON_TWISTER_HTML) is False


def test_check_price_page_captures_baseline_without_notifying(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_price_page()]}), encoding="utf-8")
    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse(AMAZON_TWISTER_HTML))

    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert sent_messages == []
    assert "baseline captured ($30.00)" in results[0]
    state = watcher._load_state()
    assert state["Price Page"]["reference_price"] == 30.00


def test_check_price_page_notifies_on_drop_past_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_price_page(threshold=10)]}), encoding="utf-8")
    # Fixture reports $30.00; set the stored reference high enough that the
    # move crosses the 10% threshold.
    watcher._save_state({"Price Page": {"reference_price": 40.00, "last_price": 40.00, "last_checked_at": "2020-01-01T00:00:00+00:00"}})
    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse(AMAZON_TWISTER_HTML))

    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    # 40 -> 30 is a -25% move, past the 10% threshold
    assert len(sent_messages) == 1
    assert "$40.00" in sent_messages[0] and "$30.00" in sent_messages[0]
    assert "-25.0%" in sent_messages[0]
    state = watcher._load_state()
    assert state["Price Page"]["reference_price"] == 30.00  # reset to new price


def test_check_price_page_skips_notify_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_price_page(threshold=10)]}), encoding="utf-8")
    watcher._save_state({"Price Page": {"reference_price": 29.00, "last_price": 29.00, "last_checked_at": "2020-01-01T00:00:00+00:00"}})
    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse(AMAZON_TWISTER_HTML))  # $30, ~3.4% move

    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert sent_messages == []
    assert "below 10% threshold" in results[0]
    # reference price is unchanged, only last_price advances
    state = watcher._load_state()
    assert state["Price Page"]["reference_price"] == 29.00
    assert state["Price Page"]["last_price"] == 30.00


def test_is_plausible_price_accepts_normal_moves():
    assert watcher._is_plausible_price(100.0, 105.0) is True
    assert watcher._is_plausible_price(100.0, 40.0) is True  # a real flash-sale-sized drop
    assert watcher._is_plausible_price(100.0, 400.0) is True  # right at the boundary


def test_is_plausible_price_rejects_extreme_jumps():
    assert watcher._is_plausible_price(1359.99, 9.99) is False  # e.g. grabbed a shipping fee
    assert watcher._is_plausible_price(9.99, 1359.99) is False


def test_check_price_page_skips_implausible_jump_without_notifying_or_persisting(tmp_path, monkeypatch):
    """A wildly wrong extraction (wrong element grabbed) must not be treated
    as a real price move — no false alarm, and the reference price must
    survive so a later good reading still compares correctly."""
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_price_page(threshold=10)]}), encoding="utf-8")
    watcher._save_state({"Price Page": {"reference_price": 1359.99, "last_price": 1359.99, "last_checked_at": "2020-01-01T00:00:00+00:00"}})
    # Fixture reports $30.00 — wildly implausible next to a $1359.99 reference.
    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse(AMAZON_TWISTER_HTML))

    sent_messages = []
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = watcher.check()

    assert sent_messages == []
    assert "implausible" in results[0]
    state = watcher._load_state()
    assert state["Price Page"]["reference_price"] == 1359.99  # untouched, will retry next cycle


def test_check_price_page_throttles_by_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(
        json.dumps({"pages": [_price_page(threshold=10, interval=240)]}), encoding="utf-8"
    )
    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    watcher._save_state({"Price Page": {"reference_price": 30.00, "last_price": 30.00, "last_checked_at": recent}})

    fetch_calls = []
    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: fetch_calls.append(1) or _FakeResponse(AMAZON_TWISTER_HTML))

    results = watcher.check()

    assert fetch_calls == []  # never fetched — still within the 240-min interval
    assert "skipped" in results[0]


def test_check_price_page_detects_captcha_block(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_price_page()]}), encoding="utf-8")
    blocked_html = "To discuss automated access to Amazon data please contact api-services-support@amazon.com."
    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse(blocked_html))

    results = watcher.check()

    assert "anti-bot/CAPTCHA" in results[0]
    assert watcher._load_state() == {}


def test_check_price_page_handles_no_price_found(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_price_page()]}), encoding="utf-8")
    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse("<html><body>no price</body></html>"))

    results = watcher.check()

    assert "no price found" in results[0]
    assert watcher._load_state() == {}


def test_check_price_page_does_not_persist_when_telegram_send_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "CONFIG_FILE", tmp_path / "page_watch_config.json")
    monkeypatch.setattr(watcher, "STATE_FILE", tmp_path / "page_watch_state.json")
    (tmp_path / "page_watch_config.json").write_text(json.dumps({"pages": [_price_page(threshold=10)]}), encoding="utf-8")
    watcher._save_state({"Price Page": {"reference_price": 40.00, "last_price": 40.00, "last_checked_at": "2020-01-01T00:00:00+00:00"}})
    monkeypatch.setattr(watcher.requests, "get", lambda url, headers, timeout: _FakeResponse(AMAZON_TWISTER_HTML))
    monkeypatch.setattr(watcher.telegram_notify, "send_message", lambda text: False)

    results = watcher.check()

    assert "will retry" in results[0]
    state = watcher._load_state()
    assert state["Price Page"]["reference_price"] == 40.00  # unchanged, retry next cycle
