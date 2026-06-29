import re

import requests

# WMO weather interpretation codes used by Open-Meteo's current_weather field.
WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}

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

    condition = WMO_CODES.get(current["weathercode"], f"code {current['weathercode']}")
    return (
        f"Weather in {label}: {current['temperature']}°F, "
        f"wind {current['windspeed']} mph, {condition}"
    )
