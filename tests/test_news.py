from datetime import datetime, timedelta, timezone

import tools.news as news
from tools.news import _parse_date


def test_parse_date_full_iso():
    result = _parse_date("2026-07-01T12:00:00+00:00")
    assert result == datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_date_relative_hours():
    before = datetime.now(timezone.utc)
    result = _parse_date("7h")
    after = datetime.now(timezone.utc)
    assert before - timedelta(hours=7, seconds=1) <= result <= after - timedelta(hours=7) + timedelta(seconds=1)


def test_parse_date_relative_days():
    result = _parse_date("2d")
    expected = datetime.now(timezone.utc) - timedelta(days=2)
    assert abs((result - expected).total_seconds()) < 5


def test_parse_date_relative_months_approximated():
    result = _parse_date("3mo")
    expected = datetime.now(timezone.utc) - timedelta(days=90)
    assert abs((result - expected).total_seconds()) < 5


def test_parse_date_relative_minutes():
    result = _parse_date("45min")
    expected = datetime.now(timezone.utc) - timedelta(minutes=45)
    assert abs((result - expected).total_seconds()) < 5


def test_parse_date_unparseable_returns_none():
    assert _parse_date("not a date") is None
    assert _parse_date("") is None


def test_parse_pubdate_rfc822():
    result = news._parse_pubdate("Wed, 08 Jul 2026 03:32:07 GMT")
    assert result == datetime(2026, 7, 8, 3, 32, 7, tzinfo=timezone.utc)


def test_parse_pubdate_invalid_returns_none():
    assert news._parse_pubdate("not a date") is None
    assert news._parse_pubdate(None) is None


GOOGLE_NEWS_SAMPLE_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Drought prompts stricter water restrictions across the Triangle - ABC11 News</title>
<link>https://news.google.com/rss/articles/abc123?oc=5</link>
<pubDate>Wed, 08 Jul 2026 03:32:07 GMT</pubDate>
<description>decorative html, not a real snippet</description>
<source url="https://abc11.com">ABC11 News</source>
</item>
</channel></rss>"""


class _FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        pass


def test_fetch_google_news_strips_duplicate_source_suffix(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _FakeResponse(GOOGLE_NEWS_SAMPLE_XML.encode()))

    items = news._fetch_google_news("Durham NC", max_results=5)

    assert len(items) == 1
    assert items[0]["title"] == "Drought prompts stricter water restrictions across the Triangle"
    assert items[0]["source"] == "ABC11 News"
    assert items[0]["url"] == "https://news.google.com/rss/articles/abc123?oc=5"
    assert items[0]["body"] == ""


def test_fetch_google_news_returns_empty_on_network_failure(monkeypatch):
    import requests

    def raise_error(*a, **k):
        raise requests.RequestException("network down")

    monkeypatch.setattr(news.requests, "get", raise_error)
    assert news._fetch_google_news("query", max_results=5) == []


def test_fetch_google_news_returns_empty_on_malformed_xml(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _FakeResponse(b"not xml"))
    assert news._fetch_google_news("query", max_results=5) == []


def _headline(title, body="", published=None):
    return {
        "title": title, "url": f"https://example.com/{title}", "source": "Example",
        "published": published or datetime.now(timezone.utc), "body": body, "image": None,
    }


def test_dedupe_merges_similar_titles_keeping_richer_body():
    items = [
        _headline("Drought prompts stricter water restrictions"),
        _headline("Drought prompts stricter water restrictions across the Triangle", body="Full details here."),
    ]
    result = news._dedupe(items)
    assert len(result) == 1
    assert result[0]["body"] == "Full details here."


def test_dedupe_keeps_unrelated_stories_separate():
    items = [_headline("Local drought worsens"), _headline("City council passes new budget")]
    assert len(news._dedupe(items)) == 2


def test_run_includes_clickable_url(monkeypatch):
    monkeypatch.setattr(news, "fetch_headlines", lambda query, max_results=5: [
        {"title": "Test Headline", "url": "https://example.com/story", "source": "Example",
         "published": datetime(2026, 7, 9, tzinfo=timezone.utc), "body": "Some details.", "image": None},
    ])
    result = news.run("test query")
    assert "https://example.com/story" in result
    assert "Test Headline" in result
    assert "2026-07-09" in result


def test_run_no_results_message(monkeypatch):
    monkeypatch.setattr(news, "fetch_headlines", lambda query, max_results=5: [])
    assert "No news" in news.run("obscure query")
