import re

import requests

# WMO weather interpretation codes used by Open-Meteo.
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

COMPASS_DIRECTIONS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

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


def _condition(code):
    return WMO_CODES.get(code, f"code {code}")


def _compass(degrees):
    if degrees is None:
        return None
    index = round(degrees / 22.5) % 16
    return COMPASS_DIRECTIONS[index]


def _geocode(query):
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 1},
            timeout=10,
        ).json()
    except requests.RequestException:
        return None
    results = geo.get("results")
    return results[0] if results else None


def _resolve_location(location):
    """Open-Meteo's geocoder is picky about trailing ', STATE' / state abbreviations,
    so fall back to progressively simpler forms of the query before giving up."""
    candidates = [location]
    no_state_abbr = re.sub(r",?\s*[A-Z]{2}$", "", location).strip()
    if no_state_abbr and no_state_abbr != location:
        candidates.append(no_state_abbr)
    if "," in location:
        candidates.append(location.split(",")[0].strip())

    for candidate in candidates:
        match = _geocode(candidate)
        if match:
            return match
    return None


def get_conditions(location):
    """Structured current conditions + 4-day forecast. Returns a dict with an
    'error' key on any failure (bad location, network issue, malformed
    response) instead of raising, so callers can degrade gracefully."""
    match = _resolve_location(location)
    if not match:
        return {
            "error": (
                f"Could not find location '{location}' in the geocoding database. "
                "Try web_search to find the official/full place name or its exact "
                "coordinates, then try again."
            )
        }

    lat, lon = match["latitude"], match["longitude"]
    label = match.get("name", location)

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                           "precipitation,weather_code,wind_speed_10m,wind_direction_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                         "precipitation_probability_max,sunrise,sunset,uv_index_max",
                "temperature_unit": "fahrenheit",
                "windspeed_unit": "mph",
                "timezone": "auto",
                "forecast_days": 4,
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        return {"error": f"Could not retrieve weather for {label}: {e}"}

    current = payload.get("current")
    daily = payload.get("daily")
    if not current or not daily:
        return {"error": f"Weather data for {label} was incomplete."}

    forecast = []
    for i, date in enumerate(daily["time"]):
        try:
            forecast.append({
                "date": date,
                "condition": _condition(daily["weather_code"][i]),
                "high": daily["temperature_2m_max"][i],
                "low": daily["temperature_2m_min"][i],
                "precip_chance": daily["precipitation_probability_max"][i],
                "uv_index": daily["uv_index_max"][i],
                "sunrise": daily["sunrise"][i],
                "sunset": daily["sunset"][i],
            })
        except (KeyError, IndexError):
            continue

    return {
        "label": label,
        "temperature": current["temperature_2m"],
        "feels_like": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "condition": _condition(current["weather_code"]),
        "wind_speed": current.get("wind_speed_10m"),
        "wind_direction": _compass(current.get("wind_direction_10m")),
        "precipitation": current.get("precipitation"),
        "forecast": forecast,
    }


def run(location):
    data = get_conditions(location)
    if "error" in data:
        return data["error"]

    feels_like = (
        f", feels like {data['feels_like']}°F" if data["feels_like"] is not None else ""
    )
    wind = ""
    if data["wind_speed"] is not None:
        direction = f" {data['wind_direction']}" if data["wind_direction"] else ""
        wind = f", wind {data['wind_speed']} mph{direction}"

    return (
        f"Weather in {data['label']}: {data['temperature']}°F{feels_like}, "
        f"{data['condition']}{wind}"
    )
