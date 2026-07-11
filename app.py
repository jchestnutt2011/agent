import concurrent.futures
import hashlib
import time

import streamlit as st
import ollama

from config import KEEP_ALIVE, MODEL, NUM_CTX
from tool_registry import load_tools
from tools import chat_log
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


def _execute_tool(call):
    """Runs in a worker thread — must not touch Streamlit (st.*) or any
    other main-thread-only API. Every tool module either does pure network
    I/O or, for shared local state (tools/memory.py), its own internal
    locking — see that module's comments for why that matters now that
    calls in the same turn can run concurrently.

    Returns a dict — {"name", "args", "content", "error"} — rather than a
    bare string: "content" is always what gets sent back to the model
    (the tool's return value, or an error string on failure, since the
    model needs to see failures to retry per SYSTEM_PROMPT), while "error"
    keeps that same information available separately so chat_log.py can
    record failures distinctly instead of string-sniffing content later."""
    name = call["function"]["name"]
    args = call["function"]["arguments"]
    func = dispatch.get(name)
    if func is None:
        content = f"Unknown tool: {name}"
        return {"name": name, "args": args, "content": content, "error": content}
    try:
        result = func(**args)
        return {"name": name, "args": args, "content": str(result), "error": None}
    except Exception as e:
        content = f"Tool {name} failed: {e}"
        return {"name": name, "args": args, "content": content, "error": content}


def run_turn(messages):
    """Call the model, executing any tool calls, until it returns a final
    answer. Logs the whole turn via chat_log.log_turn on every exit path —
    see that module for why."""
    user_message = messages[-1].get("content", "") if messages else ""
    start = time.time()
    all_tool_results = []

    for iteration in range(MAX_TOOL_ITERATIONS):
        response = ollama.chat(
            model=MODEL,
            messages=messages,
            tools=schemas,
            keep_alive=KEEP_ALIVE,
            options={"num_ctx": NUM_CTX},
        )
        msg = response["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            reply = msg.get("content", "")
            chat_log.log_turn(user_message, all_tool_results, reply, iteration + 1, time.time() - start)
            return reply

        names = ", ".join(call["function"]["name"] for call in tool_calls)
        with st.spinner(f"Running {names}..."):
            # Independent tool calls (e.g. weather + news in one turn) run
            # concurrently instead of one-at-a-time — each is its own
            # network round trip, so this cuts wall-clock time on any turn
            # that requests more than one. executor.map preserves input
            # order in its results, which matters: Ollama matches each
            # appended tool message back to its tool_call by position, not
            # by an explicit id, so results must be appended in the same
            # order tool_calls arrived in even though they didn't finish
            # in that order.
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
                tool_results = list(executor.map(_execute_tool, tool_calls))

        for tr in tool_results:
            messages.append({"role": "tool", "content": tr["content"]})
        all_tool_results.extend(tool_results)

    reply = "I wasn't able to finish that after several tool calls — could you rephrase or simplify the request?"
    chat_log.log_turn(user_message, all_tool_results, reply, MAX_TOOL_ITERATIONS, time.time() - start, hit_max_iterations=True)
    return reply


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
