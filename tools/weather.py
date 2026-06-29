import re

import requests

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather conditions for a location.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name, e.g. 'Seattle'"}
            },
            "required": ["location"]
        }
    }
}


def _geocode(query):
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": query, "count": 1},
        timeout=10,
    ).json()
    results = geo.get("results")
    return results[0] if results else None


def run(location):
    # Open-Meteo's geocoder is picky about trailing ", STATE" / state abbreviations,
    # so fall back to progressively simpler forms of the query before giving up.
    candidates = [location]
    no_state_abbr = re.sub(r",?\s*[A-Z]{2}$", "", location).strip()
    if no_state_abbr and no_state_abbr != location:
        candidates.append(no_state_abbr)
    if "," in location:
        candidates.append(location.split(",")[0].strip())

    match = None
    for candidate in candidates:
        match = _geocode(candidate)
        if match:
            break

    if not match:
        return (
            f"Could not find location '{location}' in the geocoding database. "
            "Try web_search to find the official/full place name (e.g. the nearest "
            "named city or town) or its exact coordinates, then call get_weather again."
        )

    lat, lon = match["latitude"], match["longitude"]
    label = match.get("name", location)

    weather = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
        },
        timeout=10,
    ).json()
    current = weather.get("current_weather")
    if not current:
        return f"Could not retrieve weather for {label}."

    return (
        f"Weather in {label}: {current['temperature']}°F, "
        f"wind {current['windspeed']} mph, code {current['weathercode']}"
    )
