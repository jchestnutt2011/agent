import tools.weather_alerts as weather_alerts


def test_run_checks_configured_locations_by_default(tmp_path, monkeypatch):
    config_file = tmp_path / "briefing_config.json"
    config_file.write_text('{"locations": ["Durham, NC", "Topsail Island, NC"]}', encoding="utf-8")
    monkeypatch.setattr(weather_alerts, "CONFIG_FILE", config_file)

    calls = []
    def fake_get_alerts_for(location):
        calls.append(location)
        return {"label": location, "alerts": []}
    monkeypatch.setattr(weather_alerts, "get_alerts_for", fake_get_alerts_for)

    result = weather_alerts.run()

    assert calls == ["Durham, NC", "Topsail Island, NC"]
    assert "No active severe weather alerts" in result


def test_run_with_explicit_location_ignores_config(tmp_path, monkeypatch):
    config_file = tmp_path / "briefing_config.json"
    config_file.write_text('{"locations": ["Durham, NC"]}', encoding="utf-8")
    monkeypatch.setattr(weather_alerts, "CONFIG_FILE", config_file)

    calls = []
    def fake_get_alerts_for(location):
        calls.append(location)
        return {"label": location, "alerts": []}
    monkeypatch.setattr(weather_alerts, "get_alerts_for", fake_get_alerts_for)

    weather_alerts.run(location="Raleigh, NC")

    assert calls == ["Raleigh, NC"]


def test_run_no_locations_configured_and_no_override(tmp_path, monkeypatch):
    monkeypatch.setattr(weather_alerts, "CONFIG_FILE", tmp_path / "briefing_config.json")
    result = weather_alerts.run()
    assert "No home locations are configured" in result


def test_run_flags_active_alerts(monkeypatch):
    monkeypatch.setattr(weather_alerts, "_configured_locations", lambda: ["Topsail Island, NC"])
    monkeypatch.setattr(weather_alerts, "get_alerts_for", lambda location: {
        "label": "Topsail Island",
        "alerts": [{"event": "Beach Hazards Statement", "headline": "Beach Hazards Statement in effect"}],
    })

    result = weather_alerts.run()

    assert "Active alerts found" in result
    assert "Beach Hazards Statement" in result
    assert "⚠️" in result


def test_run_reports_per_location_lookup_errors(monkeypatch):
    monkeypatch.setattr(weather_alerts, "_configured_locations", lambda: ["Nowhereville, XX"])
    monkeypatch.setattr(weather_alerts, "get_alerts_for", lambda location: {"error": "Could not find location"})

    result = weather_alerts.run()

    assert "could not check" in result


def test_run_does_not_claim_no_alerts_when_lookup_failed(monkeypatch):
    """A lookup failure must never be reported as 'No active severe weather
    alerts' — that's false confidence for a weather-safety tool."""
    monkeypatch.setattr(weather_alerts, "_configured_locations", lambda: ["Durham, NC"])
    monkeypatch.setattr(weather_alerts, "get_alerts_for", lambda location: {"error": "network down"})

    result = weather_alerts.run()

    assert "No active severe weather alerts" not in result
    assert "Could not check" in result


def test_run_mixed_alerts_and_clear_locations(monkeypatch):
    monkeypatch.setattr(weather_alerts, "_configured_locations", lambda: ["Durham, NC", "Topsail Island, NC"])

    def fake_get_alerts_for(location):
        if location == "Topsail Island, NC":
            return {"label": "Topsail Island", "alerts": [{"event": "Beach Hazards Statement", "headline": None}]}
        return {"label": "Durham", "alerts": []}

    monkeypatch.setattr(weather_alerts, "get_alerts_for", fake_get_alerts_for)

    result = weather_alerts.run()

    assert "Active alerts found" in result
    assert "Durham: no active alerts" in result
    assert "Topsail Island: ⚠️ Beach Hazards Statement" in result
