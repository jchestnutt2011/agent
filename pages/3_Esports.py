from datetime import datetime

import streamlit as st

from tools import esports

st.set_page_config(page_title="Esports Schedule", page_icon="\U0001F3AE", layout="wide")
st.title("Esports Schedule")
st.caption(
    "Upcoming professional matches via PandaScore. Cached for 15 minutes — "
    "hit refresh for the latest."
)

if not esports._load_api_key():
    st.info(
        "No PandaScore API key configured yet. Create a free account at "
        "[app.pandascore.co](https://app.pandascore.co), grab your token from "
        "the Dashboard, and save it to `pandascore_auth.json` as "
        '`{"api_key": "..."}` in the project root.'
    )
    st.stop()


@st.cache_data(ttl=900)
def fetch_upcoming(game_slug, limit=8):
    return esports.get_matches(game_slug, "upcoming", limit=limit)


refresh_col, _ = st.columns([1, 4])
with refresh_col:
    if st.button("Refresh now"):
        fetch_upcoming.clear()
        st.rerun()

selected_games = st.multiselect(
    "Games",
    options=list(esports.GAMES.keys()),
    default=list(esports.GAMES.keys()),
    format_func=lambda slug: esports.GAMES[slug],
)


def _format_when(iso_str):
    """Match times come back as UTC ('...Z'); show them in local time so
    they mean something at a glance, same reasoning as elsewhere in this
    project (current_time.py's default local-time behavior)."""
    if not iso_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return iso_str
    return dt.strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


def render_match(m):
    when = _format_when(m["scheduled_at"])
    context = " · ".join(part for part in (m.get("league"), m.get("tournament")) if part)
    bo = f"Bo{m['best_of']}" if m.get("best_of") else ""

    cols = st.columns([3, 2, 2])
    cols[0].markdown(f"**{m['team1']}** vs **{m['team2']}**")
    cols[1].caption(context or "—")
    cols[2].caption(f"{when}{'  ·  ' + bo if bo else ''}")
    if m.get("stream_url"):
        cols[2].markdown(f"[Watch]({m['stream_url']})")


if not selected_games:
    st.caption("Select at least one game above.")

for slug in selected_games:
    st.subheader(esports.GAMES[slug])
    result = fetch_upcoming(slug)

    if result["error"]:
        st.warning(result["error"])
        continue
    if not result["matches"]:
        st.caption("No upcoming matches scheduled right now.")
        continue

    for match in result["matches"]:
        with st.container(border=True):
            render_match(match)
