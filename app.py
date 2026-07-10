import hashlib

import streamlit as st
import ollama

from config import MODEL
from tool_registry import load_tools
from tools.voice_input import transcribe

st.set_page_config(page_title="Home Agent", page_icon="🤖")
st.title("Home Agent")

schemas, dispatch = load_tools()

SYSTEM_PROMPT = (
    "You are a helpful home assistant with access to tools. "
    "If a tool call fails or returns no result, do not give up or ask the user "
    "for clarification right away. Instead, try again: use web_search to find "
    "the correct name, location, or details, or rephrase your query and retry "
    "the failing tool. Only ask the user for clarification after you have tried "
    "at least one alternative approach. "
    "When the user shares information worth remembering for next time "
    "(preferences, facts about them, ongoing tasks), proactively save it with "
    "the memory tool. If a single message contains multiple distinct facts "
    "(e.g. their name AND a preference), call the memory tool once per fact, "
    "each with its own key, rather than saving only one of them. Use a "
    "descriptive snake_case key naming the fact itself (e.g. 'user_name', "
    "'temperature_unit_preference'), not the value, so you can reliably "
    "recall it later."
)

# Keep chat history across messages
if "messages" not in st.session_state:
    saved_memory = dispatch["memory"](action="list")
    st.session_state.messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Saved notes from previous conversations:\n{saved_memory}"},
    ]
if "audio_widget_key" not in st.session_state:
    st.session_state.audio_widget_key = 0
if "last_audio_hash" not in st.session_state:
    st.session_state.last_audio_hash = None

# Display chat history
for msg in st.session_state.messages:
    if msg["role"] in ("user", "assistant") and msg.get("content"):
        with st.chat_message(msg["role"]):
            st.write(msg["content"])


MAX_TOOL_ITERATIONS = 8


def run_turn(messages):
    """Call the model, executing any tool calls, until it returns a final answer."""
    for _ in range(MAX_TOOL_ITERATIONS):
        response = ollama.chat(model=MODEL, messages=messages, tools=schemas)
        msg = response["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return msg.get("content", "")

        for call in tool_calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            func = dispatch.get(name)
            if func is None:
                result = f"Unknown tool: {name}"
            else:
                with st.spinner(f"Running {name}..."):
                    try:
                        result = func(**args)
                    except Exception as e:
                        result = f"Tool {name} failed: {e}"
            messages.append({"role": "tool", "content": str(result)})

    return "I wasn't able to finish that after several tool calls — could you rephrase or simplify the request?"


def handle_user_message(prompt):
    """Shared by typed and transcribed voice input, so both go through the
    exact same tool-calling pipeline — voice is just a different way of
    producing the same text prompt, not a separate code path."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            reply = run_turn(st.session_state.messages)
            st.write(reply)


# Voice input, tucked behind a small mic icon next to the chat bar instead
# of a full-width recorder — the recorder itself only appears once the icon
# is clicked. st.audio_input keeps returning the same recording on every
# rerun until the widget is cleared (unlike st.chat_input, which
# self-resets after being read once) — dedup by content hash so a recording
# isn't transcribed and re-sent on every subsequent rerun.
_, mic_col = st.columns([12, 1])
with mic_col:
    with st.popover("🎤", use_container_width=False):
        audio = st.audio_input(
            "Record a voice message",
            key=f"audio_input_{st.session_state.audio_widget_key}",
            label_visibility="collapsed",
        )
        if audio is not None:
            audio_bytes = audio.getvalue()
            audio_hash = hashlib.md5(audio_bytes).hexdigest()
            if audio_hash != st.session_state.last_audio_hash:
                st.session_state.last_audio_hash = audio_hash
                with st.spinner("Transcribing..."):
                    transcribed = transcribe(audio_bytes)
                if transcribed:
                    st.session_state.audio_widget_key += 1  # forces a fresh, empty widget next run
                    handle_user_message(transcribed)
                    st.rerun()
                else:
                    st.warning("Couldn't make out any speech in that recording — try again.")

# Typed input
if prompt := st.chat_input("Ask anything..."):
    handle_user_message(prompt)
