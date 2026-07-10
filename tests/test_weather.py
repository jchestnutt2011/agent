import requests

from tools import weather


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_compass_cardinal_points():
    assert weather._compass(0) == "N"
    assert weather._compass(90) == "E"
    assert weather._compass(180) == "S"
    assert weather._compass(270) == "W"


def test_compass_wraps_around_360():
    assert weather._compass(360) == "N"
    assert weather._compass(359) == "N"


def test_compass_none_returns_none():
    assert weather._compass(None) is None


def test_condition_known_code():
    assert weather._condition(0) == "clear sky"
    assert weather._condition(95) == "thunderstorm"


def test_condition_unknown_code_falls_back_to_code_label():
    assert weather._condition(12345) == "code 12345"


def test_resolve_location_falls_back_past_state_abbreviation(monkeypatch):
    """Open-Meteo's geocoder rejects 'City, ST' but accepts bare city names, so
    _resolve_location should retry with the state abbreviation stripped."""
    calls = []

    def fake_geocode(query):
        calls.append(query)
        if query == "Durham":
            return {"latitude": 35.99, "longitude": -78.9, "name": "Durham"}
        return None

    monkeypatch.setattr(weather, "_geocode", fake_geocode)
    result = weather._resolve_location("Durham, NC")

    assert result == {"latitude": 35.99, "longitude": -78.9, "name": "Durham"}
    assert calls == ["Durham, NC", "Durham"]


def test_resolve_location_returns_none_when_all_candidates_fail(monkeypatch):
    monkeypatch.setattr(weather, "_geocode", lambda query: None)
    assert weather._resolve_location("Nowhereville, XX") is None


def test_get_alerts_parses_active_features(monkeypatch):
    payload = {
        "features": [
            {
                "properties": {
                    "event": "Severe Thunderstorm Warning",
                    "headline": "Severe Thunderstorm Warning issued for Durham County",
                    "severity": "Severe",
                    "description": "Damaging winds expected.",
                    "expires": "2026-07-09T20:00:00-04:00",
                }
            }
        ]
    }
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: _FakeResponse(payload))

    alerts = weather._get_alerts(35.99, -78.9)

    assert len(alerts) == 1
    assert alerts[0]["event"] == "Severe Thunderstorm Warning"
    assert alerts[0]["severity"] == "Severe"


def test_get_alerts_empty_when_no_active_alerts(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: _FakeResponse({"features": []}))
    assert weather._get_alerts(35.99, -78.9) == []


def test_get_alerts_returns_empty_list_on_failure_not_exception(monkeypatch):
    def raise_error(*a, **k):
        raise requests.RequestException("network down")

    monkeypatch.setattr(weather.requests, "get", raise_error)
    assert weather._get_alerts(35.99, -78.9) == []


def test_run_appends_alert_summary(monkeypatch):
    monkeypatch.setattr(weather, "get_conditions", lambda location: {
        "label": "Durham", "temperature": 90.0, "feels_like": 95.0, "humidity": 60,
        "condition": "clear sky", "wind_speed": 5.0, "wind_direction": "N",
        "forecast": [],
        "alerts": [{"event": "Heat Advisory", "headline": "Heat Advisory in effect", "severity": "Moderate"}],
    })
    result = weather.run("Durham")
    assert "Heat Advisory in effect" in result
