import tools.plan as plan


def test_run_drafts_critiques_and_revises_in_three_calls(monkeypatch):
    calls = []

    def fake_chat(model, messages):
        calls.append(messages[0]["content"])
        n = len(calls)
        content = {1: "DRAFT", 2: "CRITIQUE", 3: "FINAL"}[n]
        return {"message": {"content": content}}

    monkeypatch.setattr(plan.ollama, "chat", fake_chat)

    result = plan.run("plan a kitchen remodel")

    assert result == "FINAL"
    assert len(calls) == 3
    assert "plan a kitchen remodel" in calls[0]
    assert "DRAFT" in calls[1]  # critique prompt includes the draft
    assert "DRAFT" in calls[2] and "CRITIQUE" in calls[2]  # revise prompt includes both


def test_run_never_asks_the_user_a_clarifying_question_in_its_prompts():
    """The whole point of this tool is to never send the user back a
    question — assert the instruction is actually present in every prompt
    template, not just described in a docstring."""
    for template in (plan._DRAFT_PROMPT, plan._REVISE_PROMPT):
        assert "never ask" in template.lower() or "not ask" in template.lower()


def test_run_returns_error_string_instead_of_raising_on_ollama_failure(monkeypatch):
    def raise_error(model, messages):
        raise ConnectionError("ollama not running")

    monkeypatch.setattr(plan.ollama, "chat", raise_error)

    result = plan.run("plan a kitchen remodel")

    assert isinstance(result, str)
    assert "couldn't" in result.lower()


def test_run_strips_whitespace_from_model_output(monkeypatch):
    monkeypatch.setattr(
        plan.ollama, "chat", lambda model, messages: {"message": {"content": "  FINAL PLAN  \n"}}
    )
    result = plan.run("plan a birthday party")
    assert result == "FINAL PLAN"
