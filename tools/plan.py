"""Multi-pass local reasoning for open-ended planning requests (a project
timeline, an ordered plan, a structured breakdown of an ambiguous goal) —
the kind of request where a single-shot call to a 7B model reliably falls
back to asking the user clarifying questions instead of just answering.

Rather than asking, this drafts a plan against explicit stated assumptions,
self-critiques that draft, and revises once against the critique — so the
user gets a real answer plus a visible list of assumptions they can correct
afterward, instead of being interrogated up front. Three local ollama.chat
calls, not one; latency is an acceptable tradeoff for this kind of request.
"""

import ollama

from config import KEEP_ALIVE, MODEL, NUM_CTX

SCHEMA = {
    "type": "function",
    "function": {
        "name": "plan",
        "description": (
            "Reason through an open-ended planning request — a project timeline, "
            "a step-by-step plan, or a structured breakdown of an ambiguous goal "
            "— and produce a concrete answer instead of asking the user "
            "clarifying questions. Use this instead of asking the user follow-up "
            "questions whenever they ask you to plan, schedule, or break "
            "something down and the request is underspecified."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The user's planning request, verbatim or lightly summarized.",
                }
            },
            "required": ["goal"],
        },
    },
}

_DRAFT_PROMPT = """You are planning something for a user who wants a real answer, not more questions. Never ask a clarifying question. Where the request is underspecified, make the single most reasonable assumption, state it explicitly, and plan against it.

Produce a concrete, structured plan (e.g. a project timeline with phases and rough durations, or ordered steps) for the following goal.

Goal: {goal}

Format your response exactly as:
Assumptions:
- ...

Plan:
..."""

_CRITIQUE_PROMPT = """Critique the following draft plan against the goal and its own stated assumptions. Point out anything unrealistic, missing, internally inconsistent, or where an assumption was too convenient. Be specific and brief: a short list of concrete problems, not a rewrite.

Goal: {goal}

Draft plan:
{draft}"""

_REVISE_PROMPT = """Revise the draft plan below to address the critique. Keep the same format (Assumptions, then Plan). Do not ask the user anything — resolve every issue yourself by adjusting the plan or its assumptions.

Goal: {goal}

Draft plan:
{draft}

Critique:
{critique}

Final revised plan (Assumptions, then Plan):"""


def _ask(prompt):
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        keep_alive=KEEP_ALIVE,
        options={"num_ctx": NUM_CTX},
    )
    return response["message"]["content"].strip()


def run(goal):
    try:
        draft = _ask(_DRAFT_PROMPT.format(goal=goal))
        critique = _ask(_CRITIQUE_PROMPT.format(goal=goal, draft=draft))
        return _ask(_REVISE_PROMPT.format(goal=goal, draft=draft, critique=critique))
    except Exception as e:
        return f"Couldn't reason through that plan: {e}"
