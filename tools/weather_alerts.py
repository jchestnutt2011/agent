import json
from pathlib import Path

from tools.weather import get_alerts_for

CONFIG_FILE = Path(__file__).parent.parent / "briefing_config.json"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_weather_alerts",
        "description": (
            "Check for active severe weather alerts or warnings right now. "
            "Checks all configured home locations by default — use this any "
            "time the user asks if there's any severe weather, a warning, or "
            "an alert, without them having to name a specific city."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Optional. Check a specific city instead of the configured home locations, e.g. 'Raleigh, NC'.",
                }
            },
            "required": [],
        },
    },
}


def _configured_locations():
    if not CONFIG_FILE.exists():
        return []
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return config.get("locations", [])


def run(location=None):
    locations = [location] if location else _configured_locations()
    if not locations:
        return "No home locations are configured to check. Add locations to briefing_config.json, or ask about a specific city."

    lines = []
    any_alerts = False
    any_errors = False
    for loc in locations:
        result = get_alerts_for(loc)
        if "error" in result:
            any_errors = True
            lines.append(f"{loc}: could not check ({result['error']})")
            continue

        alerts = result["alerts"]
        if not alerts:
            lines.append(f"{result['label']}: no active alerts")
            continue

        any_alerts = True
        for alert in alerts:
            headline = alert.get("headline") or alert["event"]
            lines.append(f"{result['label']}: ⚠️ {alert['event']} — {headline}")

    # Distinguish "checked and clear" from "couldn't check" — a lookup
    # failure isn't the same as no alerts, and saying so would be false
    # confidence for a weather-safety tool.
    if any_alerts:
        prefix = "Active alerts found:\n"
    elif any_errors:
        prefix = "Could not check all locations for alerts:\n"
    else:
        prefix = "No active severe weather alerts.\n"

    return prefix + "\n".join(lines)
