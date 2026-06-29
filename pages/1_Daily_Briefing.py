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
        subprocess.run([sys.executable, str(SCRIPT)], cwd=BASE_DIR, check=True)
    st.rerun()

if not BRIEFING_FILE.exists():
    st.info("No briefing generated yet. Click 'Regenerate now' to create one.")
else:
    data = json.loads(BRIEFING_FILE.read_text(encoding="utf-8"))
    st.caption(f"Generated at {data['generated_at']}")
    st.markdown(data["text"])

    with st.expander("Raw data used for this briefing"):
        st.json(data["raw"])
