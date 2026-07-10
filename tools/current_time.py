from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "Get the current date and time, optionally in a specific IANA timezone.",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name, e.g. 'America/Los_Angeles'. Defaults to local system time."
                }
            },
            "required": []
        }
    }
}


def run(timezone=None):
    if timezone:
        # The model may pass a non-IANA string (e.g. "EST", "PST") or a typo,
        # which raises rather than returning. Catch it and tell the model
        # what went wrong so it can retry with a proper IANA name instead of
        # the tool crashing. ValueError covers the odd malformed key form.
        try:
            now = datetime.now(ZoneInfo(timezone))
        except (ZoneInfoNotFoundError, ValueError):
            return (
                f"'{timezone}' isn't a valid IANA timezone name. "
                "Use a full name like 'America/New_York' or 'Europe/London'."
            )
    else:
        now = datetime.now().astimezone()
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")
