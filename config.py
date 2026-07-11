MODEL = "qwen2.5:7b-instruct"

# Keep the model resident in VRAM between calls instead of Ollama's default
# (~5 min). weather_alert_monitor.py and page_watcher.py both run every 15
# minutes — longer than that default — so nearly every scheduled judgment
# call was cold-loading the model from disk before it could even start
# generating. Measured on this box: ~10GB of the 1080 Ti's 11GB was sitting
# idle between calls, so there's no VRAM pressure reason not to. 30m
# comfortably bridges the 15-minute gap (whichever caller fires next resets
# the timer) while still freeing VRAM if the whole system goes idle.
KEEP_ALIVE = "30m"

# Pinned explicitly rather than left implicit, so every caller agrees on the
# same context size — if different call sites requested different num_ctx
# values against the same loaded model, Ollama would reload it to match
# whichever one asked most recently, silently defeating KEEP_ALIVE above.
# 4096 matches Ollama's own current runtime default (confirmed via `ollama
# ps`, NOT the model's much larger declared max of 32768) — measured that
# this project's system prompt + all tool schemas alone already use ~1,100
# tokens of it, so this is already appropriately sized, not wasteful.
# Don't shrink it without re-measuring; a growing tool count eats into this
# same budget.
NUM_CTX = 4096

# {"notify": bool, "reason": str} — the exact shape weather_alert_monitor.py
# and page_watcher.py both ask the model for. Passed as an actual JSON
# schema (not the older, looser format="json") so Ollama grammar-constrains
# generation to guarantee valid, schema-conforming output — this removes
# the possibility of a malformed-JSON response from a well-behaved call
# entirely, rather than just detecting it after the fact.
NOTIFY_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "notify": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["notify", "reason"],
}
