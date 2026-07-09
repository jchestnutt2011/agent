from datetime import datetime, timedelta, timezone

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
