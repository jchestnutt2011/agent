import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).parent.parent
BRIEFING_FILE = BASE_DIR / "briefing.json"
SCRIPT = BASE_DIR / "daily_briefing.py"

st.set_page_config(page_title="Daily Briefing", page_icon="📰")
st.title("Daily Briefing")

if st.button("Regenerate now"):
    with st.spinner("Generating briefing... this can take a minute"):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=BASE_DIR, capture_output=True, text=True
        )
    if result.returncode != 0:
        st.error("Briefing generation failed. See details below.")
        st.code(result.stderr or result.stdout)
    else:
        st.rerun()

if not BRIEFING_FILE.exists():
    st.info("No briefing generated yet. Click 'Regenerate now' to create one.")
else:
    data = json.loads(BRIEFING_FILE.read_text(encoding="utf-8"))
    st.caption(f"Generated at {data['generated_at']}")
    st.markdown(data["text"])

    st.subheader("Reddit Highlights")
    for subreddit, posts in data.get("reddit", {}).items():
        st.markdown(f"**r/{subreddit}**")
        if isinstance(posts, str):
            st.markdown(f"_{posts}_")
        else:
            for post in posts:
                st.markdown(f"- [{post['title']}]({post['url']})")

    with st.expander("Raw data used for this briefing"):
        st.json(data["raw"])
