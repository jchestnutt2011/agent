"""Shared realistic-browser HTTP headers, for anywhere this project fetches
a page that might reject a bare/generic User-Agent. Proven against a real
Amazon product page: a minimal UA-only request got served a CAPTCHA wall
(opfcaptcha.amazon.com); this full header set got the real page through.

Kept as ONE definition — previously drifted into three near-identical but
different copies across tools/news.py, tools/reddit.py, and page_watcher.py
— so a future "this got blocked, try different headers" fix only needs to
happen once, and every fetch in this project gets the most battle-tested
version rather than whichever one happened to work when it was written.

Deliberately NOT used by tools/weather.py: the National Weather Service API
explicitly wants a User-Agent identifying the application and a contact
email, not a browser impersonation — a different purpose, not a duplicate
of this.
"""

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
