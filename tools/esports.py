"""Upcoming/live professional esports match schedules via PandaScore's
official API (https://api.pandascore.co) — chosen over scraping HLTV/
vlr.gg/lolesports' unofficial endpoints (the same class of "could
silently break" scraper this project already got burned by with Amazon)
and over Liquipedia's API (free tier restricted to non-commercial public
websites, and rate-limited to 60 req/hour — tighter than this needs).
Fixture/schedule endpoints are available on PandaScore's free tier across
every game this project tracks.

Optional, gitignored pandascore_auth.json: {"api_key": "..."}. Absent or
invalid, every function here degrades to a clear error string/dict rather
than raising — same pattern as tools/stocks.py's Finnhub key handling.
"""

import json
from pathlib import Path

import requests

AUTH_FILE = Path(__file__).parent.parent / "pandascore_auth.json"

API_BASE = "https://api.pandascore.co"

# PandaScore's videogame slug -> friendly display name. CS2 keeps the
# legacy "csgo" slug in PandaScore's API even though the game itself is CS2.
GAMES = {
    "dota2": "Dota 2",
    "csgo": "CS2",
    "lol": "League of Legends",
    "valorant": "Valorant",
}

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_esports_schedule",
        "description": (
            "Get upcoming professional esports matches for Dota 2, CS2, League "
            "of Legends, or Valorant. Use this whenever the user asks about "
            "esports matches, tournament schedules, or who's playing next in "
            "competitive gaming."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "game": {
                    "type": "string",
                    "enum": list(GAMES.keys()),
                    "description": "Which game to check. Omit to check all four.",
                },
            },
            "required": [],
        },
    },
}


def _load_api_key():
    if not AUTH_FILE.exists():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data.get("api_key") or None


def _normalize_match(raw, game_slug):
    """Flatten PandaScore's nested match shape into the fields this project
    actually displays. Every lookup uses .get() with a fallback — the API's
    exact shape isn't a stable contract this code should trust blindly."""
    opponents = raw.get("opponents") or []
    team_names = [(o.get("opponent") or {}).get("name") or "TBD" for o in opponents]

    streams = raw.get("streams_list") or []
    stream = next((s for s in streams if s.get("official")), streams[0] if streams else None)

    league = raw.get("league") or {}
    serie = raw.get("serie") or {}
    tournament = raw.get("tournament") or {}

    return {
        "id": raw.get("id"),
        "game": GAMES.get(game_slug, game_slug),
        "team1": team_names[0] if len(team_names) > 0 else "TBD",
        "team2": team_names[1] if len(team_names) > 1 else "TBD",
        "scheduled_at": raw.get("scheduled_at"),
        "status": raw.get("status"),
        "league": league.get("name"),
        "serie": serie.get("full_name") or serie.get("name"),
        "tournament": tournament.get("name"),
        "best_of": raw.get("number_of_games"),
        "stream_url": (stream or {}).get("raw_url"),
    }


def get_matches(game_slug, kind="upcoming", limit=10):
    """kind is 'upcoming' or 'running'. Returns {'matches': [...], 'error':
    str|None} — always both keys, error is None on success. Never raises:
    a bad/missing key, a rate limit, or a network blip all degrade to a
    clear error message rather than taking down a caller (chat tool or the
    Streamlit tab) that's checking several games in one pass."""
    if game_slug not in GAMES:
        return {"matches": [], "error": f"Unknown game '{game_slug}'. Choose from: {', '.join(GAMES)}."}

    api_key = _load_api_key()
    if not api_key:
        return {"matches": [], "error": "PandaScore API key not configured (pandascore_auth.json missing)."}

    try:
        resp = requests.get(
            f"{API_BASE}/{game_slug}/matches/{kind}",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"per_page": limit, "sort": "scheduled_at"},
            timeout=10,
        )
    except requests.RequestException as e:
        return {"matches": [], "error": f"Could not reach PandaScore: {e}"}

    if resp.status_code == 401:
        return {"matches": [], "error": "PandaScore API key was rejected (401) — check pandascore_auth.json."}
    if resp.status_code == 429:
        return {"matches": [], "error": "PandaScore rate limit hit (429) — try again shortly."}
    if resp.status_code != 200:
        return {"matches": [], "error": f"PandaScore returned HTTP {resp.status_code}."}

    try:
        raw_matches = resp.json()
    except ValueError as e:
        return {"matches": [], "error": f"Could not parse PandaScore response: {e}"}

    return {"matches": [_normalize_match(m, game_slug) for m in raw_matches], "error": None}


def _format_match_line(m):
    league = f" ({m['league']})" if m.get("league") else ""
    stream = f" — {m['stream_url']}" if m.get("stream_url") else ""
    return f"- {m['team1']} vs {m['team2']}{league} at {m['scheduled_at']}{stream}"


def run(game=None):
    games_to_check = [game] if game else list(GAMES.keys())
    lines = []

    for slug in games_to_check:
        if slug not in GAMES:
            lines.append(f"Unknown game '{slug}'. Choose from: {', '.join(GAMES)}.")
            continue

        result = get_matches(slug, "upcoming", limit=5)
        if result["error"]:
            lines.append(f"{GAMES[slug]}: {result['error']}")
            continue
        if not result["matches"]:
            lines.append(f"{GAMES[slug]}: no upcoming matches scheduled.")
            continue

        lines.append(f"{GAMES[slug]} upcoming:")
        lines.extend(_format_match_line(m) for m in result["matches"])

    return "\n".join(lines) if lines else "No esports data available."
