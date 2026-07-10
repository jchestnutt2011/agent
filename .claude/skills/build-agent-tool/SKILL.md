---
name: build-agent-tool
description: Guides building a new tool for the local AI home-assistant agent at C:\ai-agent (the Streamlit chat app in app.py, backed by a local Ollama model). Use this skill whenever the user asks to add, build, or create a new tool for their local agent, wants to give the agent a new capability, asks the agent to be able to do something it currently can't, or mentions extending C:\ai-agent's tools folder — even if they don't say the word "tool" explicitly (e.g. "I want it to be able to check X", "can we hook it up to Y", "give it access to Z", "can the agent do Y yet"). Do not use for changes to the daily briefing pipeline, Streamlit UI/pages, or memory/config that aren't about adding a new tools/*.py module.
---

# Building a tool for the local AI agent

This project's architecture: **Claude writes tools, the local Ollama model only
calls them.** The model (`qwen2.5:7b-instruct`) is not trusted to author its own
code — tools get real network/file/API-key access, and it isn't a strong enough
coder to be safe unsupervised. When the user asks for a new capability, you're
the one writing it, not the local model.

## Before you write anything

Read these — the whole point of this skill is to not duplicate them here:

1. **`tools/CONTRIBUTING.md`** — the actual contract: interface shape,
   error-handling rules, the credential-file pattern, testing and
   live-verification requirements, and a pre-done checklist. Follow it.
2. **Two or three existing tools as reference**, picked by what the new tool
   needs:
   - Fetching from a free/keyless API, failing open on errors →
     `tools/weather.py`
   - Needs a per-service credential (API key, token) → `tools/reddit.py`'s
     `_load_auth()` or `tools/stocks.py`'s `_load_finnhub_key()` (note how
     `stocks.py` also falls back to a second provider when the first isn't
     configured or fails — a good pattern when reliability matters)
   - A structured helper that isn't chat-exposed (used by the briefing or a
     Streamlit page instead) → `tools/telegram_notify.py`, or `stocks.py`'s
     `get_major_indices()` / `get_watchlist()`

## Workflow

1. **Clarify scope if the request is ambiguous.** "Give it the ability to check
   sports scores" could mean one league or all of them, live or final scores
   only, a specific team. A quick clarifying question here saves a rewrite
   later — but don't interrogate for things you can reasonably infer or that
   have an obvious default.

2. **Pick the shape**: a chat tool (`SCHEMA` + `run()`, the model calls it
   directly in conversation) or a plain helper (no `SCHEMA`, used by
   `daily_briefing.py` or a Streamlit page instead). Most requests are chat
   tools; it's a helper when the user is really describing a briefing/dashboard
   feature, not something they'd ask the chat model mid-conversation.

3. **Write it following `tools/CONTRIBUTING.md`.** The two things most often
   gotten wrong if that doc gets skipped: forgetting to catch exceptions so
   `run()` never raises, and — if a credential is needed — hardcoding it
   instead of putting it in a gitignored `{name}_auth.json`.

4. **Write tests** in `tests/test_<module>.py`: the happy path (mocked network
   calls), the "not configured" path if it has optional auth, and at least one
   failure-mode path.

5. **Live-verify it** against the real service — actually call it, don't just
   trust the mocks. Mocked tests alone have missed real bugs on this project
   before: a field silently absent from a real API response, an endpoint that
   turned out to be rate-limited or blocked in practice.

6. **Run the full suite** (`pytest tests/ -q`) before calling it done.

7. **If it needs a credential**, tell the user exactly how to get it — which
   page, which button, what the value should look like — the way past sessions
   walked through getting Reddit RSS auth params, a Finnhub key, or a Telegram
   bot token. Never ask the user to paste a secret and then hardcode it into
   source; it always lands in the gitignored auth file instead.

8. **Summarize what was built and how it activates.** For a chat tool this is
   usually "auto-discovered next time `app.py` restarts, nothing else to wire
   up" — `tool_registry.py` scans `tools/*.py` for the `SCHEMA`+`run()` shape
   on load.

## Guardrails specific to this skill

- Don't touch `daily_briefing.py`, the Streamlit pages, `tool_registry.py`, or
  `agent_memory.json`'s schema unless the request genuinely requires it — this
  skill is scoped to adding a tool, not refactoring the pipeline around it.
- Don't build a tool broader than what was asked. One tool, one purpose — see
  `tools/CONTRIBUTING.md`'s rule against scope creep.
- If the request needs something with no clean API or feed behind it (raw
  scraping a site that offers neither), say so and ask before building
  something fragile, rather than silently shipping a scraper as the only
  option without flagging the tradeoff.
