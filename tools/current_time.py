from datetime import datetime
from zoneinfo import ZoneInfo

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
        now = datetime.now(ZoneInfo(timezone))
    else:
        now = datetime.now().astimezone()
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")
