from tools import weather


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
