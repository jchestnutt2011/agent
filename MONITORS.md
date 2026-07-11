# Scheduled monitors

This project runs six things on Windows Task Scheduler, all as the local
user account, all logging to a gitignored `*.log` file in the repo root via
their `run_*.bat` wrapper. None of this is Docker/cron — it's plain `.bat`
files calling `venv\Scripts\python.exe` on a schedule, registered directly
in Task Scheduler.

| Task name | Script | Cadence | Purpose |
|---|---|---|---|
| AI Agent Daily Briefing | `daily_briefing.py` | Once/day, ~5-6am | Weather/markets/news/Reddit digest, pushed to Telegram |
| AI Agent Weather Alert Monitor | `weather_alert_monitor.py` | Every 15 min | NWS severe weather alerts → Telegram |
| AI Agent Job Watchdog | `job_watchdog.py` | Every 15 min | Detects the jobs listed in `job_watchdog_config.json` going stale or crashing |
| AI Agent Page Watcher | `page_watcher.py` | Every 15 min (price-mode entries throttled further — see note below) | Web page content/price changes → Telegram |
| AI Agent Host Health Monitor | `host_health_monitor.py` | Every 15 min | Disk space, Ollama/Streamlit reachability on this PC |
| AI Agent Chat Log Rotate | `chat_log_rotate.py` | Weekly, Sunday 3am | Rotates `chat_log.jsonl` so it doesn't grow unbounded |

## Per-monitor files

Each monitor (all but the daily briefing) follows the same shape:

- **`run_<name>.bat`** — launches `venv\Scripts\python.exe <name>.py`,
  redirects stdout/stderr to `<name>.log` (gitignored, `*.log`).
- **`<name>_config.json`** — committed. What to watch/check and thresholds.
  Hand-editable, or (for page_watcher's price mode) editable from the
  Streamlit **Price Watch** page instead.
- **`<name>_state.json`** — gitignored (listed explicitly in `.gitignore`,
  not just `*.json`, since config files are also `.json` and ARE
  committed). What's already been seen/decided, so a monitor doesn't
  re-evaluate or re-notify every cycle. Safe to delete — the monitor
  rebuilds it from scratch on the next run (may cause one round of
  "baseline captured" no-op lines).
- **`state_store.py`** (shared) — every monitor's `_load_state()`/
  `_save_state()` delegate here for the atomic-write JSON load/save
  boilerplate, plus `file_lock`/`merge_json_state` for the one file
  (`page_watch_state.json`/`page_watch_config.json`) that's written by
  more than one process (the scheduled run AND the Streamlit UI).

Page Watcher's price-mode entries (`price_threshold_pct` set on a page)
don't actually fetch on every 15-minute cycle — each has its own
`check_interval_minutes` (default 4h, configurable per-page from the Price
Watch UI). Deliberately slower than the script's own cadence: repeatedly
hitting a site like Amazon risks it blocking the request pattern, and
prices don't need 15-minute granularity anyway. See `page_watcher.py`'s
module docstring for the live-observed CAPTCHA-block details.

`chat_log.jsonl` (gitignored) is app.py's running log of every chat
turn — see `tools/chat_log.py`'s module docstring for why it exists (no
mechanism previously existed to look back at real usage and let that
inform new tool ideas). `chat_log_rotate.py` doesn't delete it weekly, it
rotates it: the just-finished week is renamed to `chat_log.jsonl.previous`
(also gitignored, overwritten each time — exactly one prior week is ever
kept), so there's always at least a week of history available to review,
never zero. `chat_log_rotate.py` is itself one of `job_watchdog.py`'s
watched jobs (see `job_watchdog_config.json`) — a broken rotation would
otherwise defeat its own purpose by failing silently while the log grows
unbounded anyway.

Credentials live in gitignored `{name}_auth.json` files at the repo root
(`telegram_auth.json`, `finnhub_auth.json`, `reddit_auth.json`) — see
`tools/CONTRIBUTING.md` for the pattern. Every monitor that sends
notifications goes through `tools/telegram_notify.py`, which silently
no-ops if `telegram_auth.json` is missing.

## Common design pattern

All four non-briefing monitors are edge-triggered, not level-triggered:
they persist a status/hash/id in their state file and only act (notify,
re-decide) when something actually *changes*, not on every 15-minute tick.
This is deliberate and has bitten this project when skipped — see the
`weather_alert_monitor.py` module docstring and job_watchdog's for the
specific incidents (a reissued NWS alert re-notifying every cycle because
its content hash included a per-reissue timestamp; a job's state getting
pruned by a stale `expires` field and looking "new" again next cycle).

Where a monitor makes a judgment call below a hard threshold (is this
weather alert worth a ping, is this page change meaningful or noise), it
asks the local Ollama model via `config.MODEL`. Where the decision is a
plain number (severity floor, price percent-change), it's a deterministic
check, not a model call — see the "Deterministic, not LLM-touched" comments
throughout for why (a small local model has no business rewriting prices).

## Adding a new monitor

1. Copy the shape of `host_health_monitor.py` (simplest existing example):
   module docstring explaining *why* this needs to exist and what could go
   wrong without it, `_load_config`/`_load_state`/`_save_state` (delegate
   to `state_store`), a `check()` that returns human-readable result lines
   and never raises, a `main()` that prints them.
2. Write `tests/test_<name>.py` — mock the network/model, cover the happy
   path, the "not configured" path if relevant, and at least one failure
   mode. Run `pytest tests/ -q`.
3. Live-verify against the real dependency at least once (per
   `tools/CONTRIBUTING.md` rule 7) — mocked tests won't catch a real API
   shape mismatch or a site blocking the request pattern.
4. Add `<name>_state.json` to `.gitignore` (explicit filename, not a glob).
5. Write `run_<name>.bat`:
   ```bat
   @echo off
   "C:\ai-agent\venv\Scripts\python.exe" "C:\ai-agent\<name>.py" >> "C:\ai-agent\<name>.log" 2>&1
   ```
6. Register the Task Scheduler entry (PowerShell, matching the existing
   tasks' settings). For a 15-minute-repeating job:
   ```powershell
   $action = New-ScheduledTaskAction -Execute "C:\ai-agent\run_<name>.bat"
   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
   $principal = New-ScheduledTaskPrincipal -UserId "<username>" -LogonType Interactive -RunLevel Limited
   $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 72) -MultipleInstances IgnoreNew
   Register-ScheduledTask -TaskName "AI Agent <Name>" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "..."
   ```
   For a weekly job (see `chat_log_rotate.py`'s registration), swap the
   trigger for `New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am`
   (pick a low-traffic day/time) and shrink `ExecutionTimeLimit` to
   something sane for the job (1 hour, not 72).
7. `Start-ScheduledTask -TaskName "AI Agent <Name>"` once to confirm it
   actually runs clean (`Get-ScheduledTaskInfo` should show
   `LastTaskResult: 0`) before considering it done.

## Debugging a monitor that isn't behaving

- Check `<name>.log` first — every run appends its result lines there.
- Check `<name>_state.json` — this is almost always where a "why didn't it
  notify me" or "why did it notify me again" question gets answered. A
  monitor's state file is the single source of truth for what it thinks
  it already knows.
- Check `Get-ScheduledTaskInfo -TaskName "AI Agent <Name>"` for
  `LastRunTime`/`LastTaskResult` — confirms Task Scheduler is actually
  firing it and the process exited 0, independent of whether the logic
  inside did the right thing.
- The Job Watchdog (`job_watchdog.py`) exists specifically to catch the
  jobs listed in `job_watchdog_config.json` (currently: weather monitor,
  daily briefing, chat log rotate) going silently stale or crashing — but
  it doesn't watch itself or the page/host monitors. If in doubt, check
  their logs and Task Scheduler info directly.
