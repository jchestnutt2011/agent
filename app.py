import streamlit as st
import ollama

from tool_registry import load_tools

st.set_page_config(page_title="Home Agent", page_icon="🤖")
st.title("Home Agent")

MODEL = "qwen2.5:7b-instruct"
schemas, dispatch = load_tools()

SYSTEM_PROMPT = (
    "You are a helpful home assistant with access to tools. "
    "If a tool call fails or returns no result, do not give up or ask the user "
    "for clarification right away. Instead, try again: use web_search to find "
    "the correct name, location, or details, or rephrase your query and retry "
    "the failing tool. Only ask the user for clarification after you have tried "
    "at least one alternative approach. "
    "At the start of a conversation, use the memory tool (action='list' or "
    "'recall') to check for relevant saved notes before assuming you don't know "
    "something. When the user shares information worth remembering for next "
    "time (preferences, facts about them, ongoing tasks), proactively save it "
    "with the memory tool."
)

# Keep chat history across messages
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# Display chat history
for msg in st.session_state.messages:
    if msg["role"] in ("user", "assistant") and msg.get("content"):
        with st.chat_message(msg["role"]):
            st.write(msg["content"])


def run_turn(messages):
    """Call the model, executing any tool calls, until it returns a final answer."""
    while True:
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


# Chat input
if prompt := st.chat_input("Ask anything..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            reply = run_turn(st.session_state.messages)
            st.write(reply)
