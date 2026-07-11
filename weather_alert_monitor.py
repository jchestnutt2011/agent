"""Runs on a schedule (every 15 min via Windows Task Scheduler). Checks the
configured home locations for new NWS alerts and decides whether each one is
worth a proactive Telegram ping.

Decision rule: Severe/Extreme severity always notifies — that's a hard floor,
not something left to the local model's judgment, since a model being wrong
about a genuinely dangerous alert is a real cost. Everything below that
threshold gets the local model's judgment call, because plenty of Moderate/
Minor alerts genuinely are worth a heads-up (e.g. rip currents at a beach
house) while most aren't, and a simple severity cutoff can't tell the
difference — that's exactly the kind of nuance an LLM reading the actual
description is suited for.

Dedup is by NWS's own alert id, persisted in alert_monitor_state.json, so an
ongoing alert doesn't get re-evaluated (or re-pinged) every single cycle. A
state entry sticks around for as long as NWS keeps returning that id in
/alerts/active — NOT until its self-reported `expires` timestamp, which can
lag reality by hours. See `_prune_stale`.
Simplification: this treats each alert id as evaluated exactly once for its
lifetime — if NWS meaningfully updates an in-place alert without changing its
id, the update won't trigger a fresh decision. Acceptable for v1; revisit if
it turns out to matter in practice.

NWS also routinely reissues some products (Beach Hazards Statement, Small
Craft Advisory, etc.) on a fixed cycle as a brand-new alert id with identical
content — id-only dedup would treat each reissue as new and re-notify every
cycle. So alerts are also deduped by a content fingerprint (location + event
+ description) against every still-active, already-seen alert: a content
match is recorded (so future reissues of the same text keep matching) but
never re-decided or re-sent. The fingerprint deliberately excludes the
headline, which always embeds a per-reissue issuance timestamp and would
otherwise make every reissue hash differently.
"""

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path

import ollama

import state_store
from config import KEEP_ALIVE, MODEL, NOTIFY_DECISION_SCHEMA, NUM_CTX
from tools.weather import get_alerts_for
from tools import telegram_notify

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "briefing_config.json"
STATE_FILE = BASE_DIR / "alert_monitor_state.json"

HARD_NOTIFY_SEVERITIES = {"severe", "extreme"}


def _load_config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _load_state():
    return state_store.load_json_state(STATE_FILE)


def _save_state(state):
    state_store.save_json_state(STATE_FILE, state)


def _prune_stale(state, seen_ids, checked_locations):
    """Drop state entries for alerts NWS is no longer actively serving, so the
    state file doesn't grow forever.

    Presence in the latest fetch (`seen_ids`) is the authoritative "still
    active" signal — NOT the alert's self-reported `expires` field, which can
    lag well behind reality. This was a real bug: an alert's `expires` had
    already passed by several hours while NWS's /alerts/active feed kept
    serving it as active with the same id. Pruning by `expires` alone evicted
    it from state every cycle, so it looked brand new on the next 15-minute
    run and got re-decided and re-notified over and over.

    `expires` is only a fallback for ids NWS has stopped returning — but only
    for a location that was actually successfully checked this cycle. If a
    location's fetch failed (network blip, NWS outage), none of its alerts
    make it into seen_ids either, which looks identical to "NWS stopped
    serving these" — a second way to trip the same bug: a transient fetch
    error could evict a genuinely still-active alert just as easily as an
    expires lag could. checked_locations distinguishes the two: an entry
    whose location wasn't successfully checked this cycle is kept
    regardless of expires, since there's no fresh evidence either way.

    Residual simplification: a location later removed from config entirely
    is never "successfully checked" again, so its entries are kept forever
    rather than eventually pruned. Acceptable for v1 — same spirit as this
    file's other documented simplifications."""
    now = datetime.now(timezone.utc)
    kept = {}
    for alert_id, entry in state.items():
        if alert_id in seen_ids:
            kept[alert_id] = entry
            continue
        if entry.get("location") not in checked_locations:
            kept[alert_id] = entry
            continue
        expires = entry.get("expires")
        if expires:
            try:
                if datetime.fromisoformat(expires) >= now:
                    kept[alert_id] = entry
            except ValueError:
                kept[alert_id] = entry
    return kept


def _ask_model_to_decide(location, alert):
    """For alerts below the hard severity floor: ask the local model whether
    this is worth proactively notifying about. format=NOTIFY_DECISION_SCHEMA
    grammar-constrains generation to that exact shape, so a well-behaved
    call cannot return malformed JSON — the except below is defense against
    Ollama itself being unreachable/erroring, not against bad output."""
    prompt = (
        "A weather alert was just issued. Decide whether a homeowner should "
        "be proactively pinged about it on their phone right now, or whether "
        "it's minor enough to skip and let them find out on their own next "
        "time they check the weather. Err toward NOT notifying for routine "
        "or minor conditions — only say yes if it's something a reasonable "
        "person would genuinely want to know about immediately.\n\n"
        f"Location: {location}\n"
        f"Event: {alert['event']}\n"
        f"Severity: {alert.get('severity')}\n"
        f"Urgency: {alert.get('urgency')}\n"
        f"Certainty: {alert.get('certainty')}\n"
        f"Headline: {alert.get('headline')}\n"
        f"Description: {(alert.get('description') or '')[:600]}\n\n"
        'Respond with only JSON: {"notify": true or false, "reason": "one short sentence"}'
    )
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            format=NOTIFY_DECISION_SCHEMA,
            keep_alive=KEEP_ALIVE,
            options={"num_ctx": NUM_CTX},
        )
        decision = json.loads(response["message"]["content"])
        return bool(decision.get("notify")), str(decision.get("reason") or "no reason given")
    except Exception as e:
        # Ollama unreachable, timed out, or some other failure shouldn't
        # crash the monitor or block future alerts — skip this one with a
        # clear reason and move on.
        return False, f"model decision failed, skipped as a precaution: {e}"


def _decide(location, alert):
    """Returns (should_notify, reason, decided_by)."""
    severity = (alert.get("severity") or "").lower()
    if severity in HARD_NOTIFY_SEVERITIES:
        return True, f"severity is {alert.get('severity')}", "hard floor"

    notify, reason = _ask_model_to_decide(location, alert)
    return notify, reason, "local model"


def _content_key(location, alert):
    """Fingerprint of an alert's actual content, independent of its (possibly
    reissued-with-a-new-id) NWS id — used to catch reissues of unchanged
    alerts that id-based dedup alone would miss.

    Deliberately excludes the headline. NWS headlines always embed the
    issuance timestamp ("...issued July 9 at 8:01PM EDT until July 10 at
    8:00PM EDT..."), which is unique to every reissue by construction — if it
    were included here, the hash would differ on every single reissue and
    this dedup would never fire. That was a real bug: Beach Hazards
    Statement got re-notified every 15 minutes for hours because of it."""
    text = "|".join([
        location, alert.get("event") or "",
        (alert.get("description") or "").strip(),
    ])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_notification(location, alert, reason):
    return (
        f"\U0001F326️ <b>Weather alert — {html.escape(location)}</b>\n"
        f"<b>{html.escape(alert['event'])}</b> ({html.escape(alert.get('severity') or 'Unknown')})\n"
        f"{html.escape(alert.get('headline') or '')}\n\n"
        f"<i>{html.escape(reason)}</i>"
    )


def check():
    """Runs one monitoring pass. Returns a list of human-readable result lines
    (also used as the log output when run via the scheduled task)."""
    config = _load_config()
    state = _load_state()
    known_content_keys = {entry["content_key"] for entry in state.values() if entry.get("content_key")}
    results = []
    seen_ids = set()
    checked_locations = set()

    for location in config.get("locations", []):
        result = get_alerts_for(location)
        if "error" in result:
            results.append(f"{location}: could not check ({result['error']})")
            continue

        checked_locations.add(result["label"])
        for alert in result["alerts"]:
            alert_id = alert.get("id")
            if not alert_id:
                continue  # can't dedup without an id; skip rather than risk spamming
            seen_ids.add(alert_id)
            if alert_id in state:
                continue  # already evaluated this alert's lifetime

            content_key = _content_key(result["label"], alert)
            if content_key in known_content_keys:
                # Same content as an already-handled alert, just reissued under a
                # new id (NWS does this routinely for some products) — record the
                # new id so it's not re-checked again, but don't re-decide or re-send.
                results.append(f"{result['label']}: {alert['event']} — duplicate of an already-handled alert, skipped")
                state[alert_id] = {
                    "location": result["label"], "event": alert["event"],
                    "severity": alert.get("severity"), "expires": alert.get("expires"),
                    "decided_by": "duplicate content", "reason": "unchanged reissue of an already-handled alert",
                    "notified": False, "content_key": content_key,
                }
                continue

            should_notify, reason, decided_by = _decide(result["label"], alert)

            if should_notify:
                message = _build_notification(result["label"], alert, reason)
                sent = telegram_notify.send_message(message)
                if not sent:
                    results.append(
                        f"{result['label']}: {alert['event']} — decided to notify but "
                        "Telegram send failed, will retry next run"
                    )
                    continue  # don't persist state — retry the full decision next cycle

                results.append(f"{result['label']}: {alert['event']} — notified ({decided_by}: {reason})")
            else:
                results.append(f"{result['label']}: {alert['event']} — skipped ({decided_by}: {reason})")

            state[alert_id] = {
                "location": result["label"], "event": alert["event"],
                "severity": alert.get("severity"), "expires": alert.get("expires"),
                "decided_by": decided_by, "reason": reason, "notified": should_notify,
                "content_key": content_key,
            }
            known_content_keys.add(content_key)

    state = _prune_stale(state, seen_ids, checked_locations)
    _save_state(state)
    return results


def main():
    results = check()
    if not results:
        print("No new alerts to evaluate.")
    for line in results:
        print(line)


if __name__ == "__main__":
    main()
