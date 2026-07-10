from datetime import datetime, timedelta, timezone

import weather_alert_monitor as monitor


def _alert(id="urn:test:1", event="Beach Hazards Statement", severity="Moderate", expires=None):
    return {
        "id": id, "event": event, "severity": severity,
        "urgency": "Expected", "certainty": "Likely",
        "headline": f"{event} in effect", "description": "Details here.",
        "expires": expires or (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
    }


def test_prune_expired_drops_past_alerts():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    state = {
        "expired-one": {"expires": past},
        "still-active": {"expires": future},
        "no-expiry": {},
    }
    result = monitor._prune_expired(state)
    assert "expired-one" not in result
    assert "still-active" in result
    assert "no-expiry" in result


def test_decide_severe_uses_hard_floor_without_calling_model(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("should not call the model for a Severe alert")
    monkeypatch.setattr(monitor, "_ask_model_to_decide", fail_if_called)

    should_notify, reason, decided_by = monitor._decide("Durham, NC", _alert(severity="Severe"))

    assert should_notify is True
    assert decided_by == "hard floor"


def test_decide_extreme_uses_hard_floor(monkeypatch):
    monkeypatch.setattr(monitor, "_ask_model_to_decide", lambda *a: (False, "should not be used"))
    should_notify, reason, decided_by = monitor._decide("Durham, NC", _alert(severity="Extreme"))
    assert should_notify is True
    assert decided_by == "hard floor"


def test_decide_moderate_defers_to_model(monkeypatch):
    monkeypatch.setattr(monitor, "_ask_model_to_decide", lambda location, alert: (True, "rip current risk"))
    should_notify, reason, decided_by = monitor._decide("Topsail Island, NC", _alert(severity="Moderate"))
    assert should_notify is True
    assert decided_by == "local model"
    assert reason == "rip current risk"


def test_ask_model_to_decide_parses_valid_json(monkeypatch):
    monkeypatch.setattr(monitor.ollama, "chat", lambda model, messages, format: {
        "message": {"content": '{"notify": true, "reason": "rip currents"}'}
    })
    notify, reason = monitor._ask_model_to_decide("Topsail Island, NC", _alert())
    assert notify is True
    assert reason == "rip currents"


def test_ask_model_to_decide_handles_malformed_json_safely(monkeypatch):
    monkeypatch.setattr(monitor.ollama, "chat", lambda model, messages, format: {
        "message": {"content": "not valid json"}
    })
    notify, reason = monitor._ask_model_to_decide("Topsail Island, NC", _alert())
    assert notify is False
    assert "precaution" in reason


def test_ask_model_to_decide_handles_ollama_exception_safely(monkeypatch):
    def raise_error(*a, **k):
        raise ConnectionError("ollama not running")
    monkeypatch.setattr(monitor.ollama, "chat", raise_error)
    notify, reason = monitor._ask_model_to_decide("Topsail Island, NC", _alert())
    assert notify is False
    assert "precaution" in reason


def test_check_skips_already_evaluated_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "briefing_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "alert_monitor_state.json")
    (tmp_path / "briefing_config.json").write_text('{"locations": ["Durham, NC"]}', encoding="utf-8")

    alert = _alert(id="already-seen")
    monitor._save_state({"already-seen": {"expires": alert["expires"]}})

    decide_calls = []
    monkeypatch.setattr(monitor, "get_alerts_for", lambda loc: {"label": loc, "alerts": [alert]})
    monkeypatch.setattr(monitor, "_decide", lambda *a: decide_calls.append(a) or (True, "x", "hard floor"))

    results = monitor.check()

    assert decide_calls == []
    assert results == []


def test_check_notifies_and_persists_state_on_new_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "briefing_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "alert_monitor_state.json")
    (tmp_path / "briefing_config.json").write_text('{"locations": ["Topsail Island, NC"]}', encoding="utf-8")

    alert = _alert(id="new-alert", severity="Severe")
    monkeypatch.setattr(monitor, "get_alerts_for", lambda loc: {"label": loc, "alerts": [alert]})

    sent_messages = []
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = monitor.check()

    assert len(sent_messages) == 1
    assert "Beach Hazards Statement" in sent_messages[0]
    assert "notified" in results[0]

    state = monitor._load_state()
    assert state["new-alert"]["notified"] is True


def test_check_does_not_persist_state_when_telegram_send_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "briefing_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "alert_monitor_state.json")
    (tmp_path / "briefing_config.json").write_text('{"locations": ["Topsail Island, NC"]}', encoding="utf-8")

    alert = _alert(id="retry-me", severity="Extreme")
    monkeypatch.setattr(monitor, "get_alerts_for", lambda loc: {"label": loc, "alerts": [alert]})
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: False)

    results = monitor.check()

    assert "will retry" in results[0]
    assert monitor._load_state() == {}  # not persisted — must be retried next cycle


def test_check_skips_low_severity_when_model_says_no(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "briefing_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "alert_monitor_state.json")
    (tmp_path / "briefing_config.json").write_text('{"locations": ["Durham, NC"]}', encoding="utf-8")

    alert = _alert(id="minor-alert", severity="Minor")
    monkeypatch.setattr(monitor, "get_alerts_for", lambda loc: {"label": loc, "alerts": [alert]})
    monkeypatch.setattr(monitor, "_ask_model_to_decide", lambda location, a: (False, "routine, no action needed"))

    sent_messages = []
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = monitor.check()

    assert sent_messages == []
    assert "skipped" in results[0]
    assert monitor._load_state()["minor-alert"]["notified"] is False


def test_check_skips_reissued_alert_with_new_id_but_same_content(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "briefing_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "alert_monitor_state.json")
    (tmp_path / "briefing_config.json").write_text('{"locations": ["Topsail Island, NC"]}', encoding="utf-8")

    original = _alert(id="original-id")
    content_key = monitor._content_key("Topsail Island, NC", original)
    monitor._save_state({
        "original-id": {
            "location": "Topsail Island, NC", "event": original["event"],
            "severity": original["severity"], "expires": original["expires"],
            "decided_by": "local model", "reason": "rip currents", "notified": True,
            "content_key": content_key,
        }
    })

    reissued = _alert(id="reissued-id")  # same event/headline/description, new id
    monkeypatch.setattr(monitor, "get_alerts_for", lambda loc: {"label": loc, "alerts": [reissued]})

    decide_calls = []
    monkeypatch.setattr(monitor, "_decide", lambda *a: decide_calls.append(a) or (True, "x", "hard floor"))
    sent_messages = []
    monkeypatch.setattr(monitor.telegram_notify, "send_message", lambda text: sent_messages.append(text) or True)

    results = monitor.check()

    assert decide_calls == []
    assert sent_messages == []
    assert "duplicate" in results[0]
    state = monitor._load_state()
    assert state["reissued-id"]["notified"] is False
    assert state["reissued-id"]["content_key"] == content_key


def test_check_handles_location_lookup_error(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "briefing_config.json")
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "alert_monitor_state.json")
    (tmp_path / "briefing_config.json").write_text('{"locations": ["Nowhereville, XX"]}', encoding="utf-8")
    monkeypatch.setattr(monitor, "get_alerts_for", lambda loc: {"error": "not found"})

    results = monitor.check()
    assert "could not check" in results[0]
