import re

from tools import current_time


def test_run_local_time_default():
    result = current_time.run()
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result)


def test_run_valid_iana_timezone():
    result = current_time.run("America/New_York")
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result)


def test_run_invalid_timezone_returns_message_not_raise():
    result = current_time.run("PST")  # common abbreviation, not a valid IANA name
    assert "isn't a valid IANA timezone" in result


def test_run_garbage_timezone_returns_message_not_raise():
    result = current_time.run("Not/A/Zone")
    assert "isn't a valid IANA timezone" in result
