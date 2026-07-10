# Writing a tool for this agent

This project's architecture: **Claude writes tools, the local Ollama model
(`qwen2.5:7b-instruct`) only calls them.** The local model is not trusted to
author or deploy its own code — it's not a strong enough coder for that to be
safe unsupervised, and tools here get real network/file/API-key access. Every
tool in this directory should be written (or reviewed) by Claude, tested, and
live-verified before it's considered done.

This doc is the contract new tools need to follow. `tools/README.md` (if you're
looking for a shorter version) doesn't exist — this is the one doc.

## Two kinds of module in `tools/`

**Chat tools** — discovered automatically by `tool_registry.load_tools()` and
exposed to the local model. A module becomes a chat tool by exposing exactly
two things:

```python
SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_thing",
        "description": "One sentence. What it does and when to use it.",
        "parameters": {
            "type": "object",
            "properties": {
                "arg": {"type": "string", "description": "..."}
            },
            "required": ["arg"],
        },
    },
}

def run(arg):
    ...
    return "a string the model reads back"
```

`tool_registry.py` scans every module in `tools/` and only wires up the ones
with both `SCHEMA` and `run` — anything else is silently skipped. So:

**Plain helper modules** — no `SCHEMA`/`run`, not exposed to the chat model,
imported directly by `daily_briefing.py` or the Streamlit pages instead. E.g.
`tools/stocks.py` also exports `get_major_indices()`/`get_watchlist()` (used
only by the briefing, not chat), and `tools/telegram_notify.py` has no chat
tool at all — it's pure plumbing. Use this shape when something is structured
data or a side effect, not a natural "ask the model a question" tool.

## Rules, synthesized from every tool in this codebase

1. **Never raise out of `run()`.** Catch exceptions, return a descriptive
   string (chat tools) or a dict with an `"error"` key (structured helpers).
   One failing tool must never crash the chat loop or take down the rest of
   a daily briefing — see `daily_briefing.py`'s `_safe()` wrapper and every
   `except (requests.RequestException, ...)` in `tools/weather.py`,
   `tools/news.py`, `tools/stocks.py`.

2. **Every network call gets a `timeout` (10s is the convention here).** No
   exceptions.

3. **Credentials go in a gitignored `{name}_auth.json` at the repo root**,
   never hardcoded, never in `briefing_config.json` (that file IS committed).
   Follow the existing pattern exactly — see `tools/reddit.py`'s
   `_load_auth()`, `tools/stocks.py`'s `_load_finnhub_key()`, or
   `tools/telegram_notify.py`'s `_load_auth()`:
   - `AUTH_FILE = Path(__file__).parent.parent / "{name}_auth.json"`
   - A loader that returns `None`/`{}` if the file is missing or malformed
     (`json.JSONDecodeError` caught, never raised)
   - The tool **degrades gracefully with no config** — usually a fallback
     to another provider (`tools/stocks.py`: Finnhub → yfinance) or a
     silent no-op (`tools/telegram_notify.py`: returns `False`), never an
     error state a user has to explicitly opt out of.
   - **Add the filename to `.gitignore` before creating the file**, then
     run `git check-ignore -v {name}_auth.json` to confirm before the file
     ever has a real credential in it. This repo is public.
   - If you need the credential's value from the user, tell them exactly
     how to get it (which page, which button) — see how the Reddit RSS
     auth params and the Finnhub/Telegram setup were requested in past
     sessions for the tone/specificity to match.

4. **Prefer official/structured APIs over scraping.** `ddgs` and `yfinance`
   are both unofficial scrapers and have both caused real breakage this
   project has already hit (rate limits, IP bans, silent format changes).
   When there's a real API (even an unauthenticated one, like Open-Meteo or
   Google News RSS) prefer it, and keep the scraper as a fallback rather
   than the primary source if one already exists.

5. **Pin new dependencies** in `requirements.txt` to the exact version
   installed (`pip show <package>`), not a bare name. Dev-only deps (like
   `pytest`) go in `requirements-dev.txt` instead.

6. **Write tests in `tests/test_<module>.py`.** At minimum:
   - The happy path, with `requests.get`/`.post` (or the relevant client)
     mocked via `monkeypatch` — never hit the real network in a test.
   - The "not configured" path, if the tool has optional auth (assert it
     falls back / no-ops rather than erroring).
   - At least one failure-mode path (network exception, malformed
     response, empty result) returning the graceful fallback, not raising.

7. **Live-verify before calling it done.** Unit tests with mocks won't catch
   things like: a field silently missing from the real response, an
   endpoint that's actually rate-limited or blocked, or a UI that renders
   wrong against real data. Actually call the real API/service at least
   once. Real bugs caught only this way in this project: `news.py` fetching
   a `url` field that the formatter never used, Reddit's unauthenticated
   `.json` endpoint returning 403, a live Telegram message coming in at
   3630/4096 characters — none of these would show up in a mocked test.

8. **For anything Streamlit-facing, verify with `streamlit.testing.v1.AppTest`**
   (`AppTest.from_file(path).run()`), not just an HTTP fetch — Streamlit runs
   scripts over websocket after the client connects, so a plain `requests.get`
   never actually executes the page's Python and won't catch a runtime
   exception in it.

9. **Keep `SCHEMA` descriptions tight and single-purpose.** The model reads
   these to decide when to call the tool — vague or overlapping
   descriptions cause it to pick the wrong tool or the wrong arguments.
   Match the terseness of the existing schemas.

10. **Don't scope-creep.** A tool should do one thing. If a feature needs
    both a chat tool and a plain helper (like `stocks.py`), that's fine —
    keep them in the same file, but keep each function focused.

## Before considering a tool done

- [ ] `SCHEMA` + `run()` present (chat tool) or deliberately absent (helper)
- [ ] No raised exceptions from `run()` under any failure mode you can think of
- [ ] Credentials (if any) in a gitignored `{name}_auth.json`, verified with
      `git check-ignore -v`
- [ ] New dependencies pinned in `requirements.txt`
- [ ] `tests/test_<module>.py` written, full suite passes (`pytest tests/ -q`)
- [ ] Live-verified against the real service at least once
- [ ] If Streamlit-facing: verified via `AppTest`
- [ ] Committed with a message explaining *why*, not just *what*
