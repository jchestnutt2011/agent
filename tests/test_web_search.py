from tools import web_search


class _FakeDDGS:
    """Context-manager stand-in for ddgs.DDGS with a scripted text() result."""
    def __init__(self, results=None, raise_on_text=None):
        self._results = results or []
        self._raise = raise_on_text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, max_results=5):
        if self._raise:
            raise self._raise
        return self._results


def test_run_formats_results(monkeypatch):
    monkeypatch.setattr(web_search, "DDGS", lambda: _FakeDDGS(results=[
        {"title": "Result One", "body": "Some body.", "href": "https://example.com/1"},
    ]))
    result = web_search.run("anything")
    assert "Result One" in result
    assert "https://example.com/1" in result


def test_run_returns_message_on_no_results(monkeypatch):
    monkeypatch.setattr(web_search, "DDGS", lambda: _FakeDDGS(results=[]))
    assert web_search.run("obscure") == "No results found."


def test_run_does_not_raise_on_ddgs_exception(monkeypatch):
    monkeypatch.setattr(web_search, "DDGS", lambda: _FakeDDGS(raise_on_text=RuntimeError("rate limited")))
    result = web_search.run("anything")
    assert "Web search failed" in result
    assert "rate limited" in result


def test_run_tolerates_missing_result_fields(monkeypatch):
    """A result dict missing title/body/href must not KeyError."""
    monkeypatch.setattr(web_search, "DDGS", lambda: _FakeDDGS(results=[{}]))
    result = web_search.run("anything")
    assert "(no title)" in result
