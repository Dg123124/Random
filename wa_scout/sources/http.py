"""Polite HTTP fetching with a disk cache and a rate limit (stdlib only)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
MIN_INTERVAL_SECONDS = float(os.environ.get("WA_SCOUT_DELAY", "2.0"))
_last_request = 0.0
_rate_lock = threading.Lock()


class FetchError(RuntimeError):
    pass


def _cache_path(key: str) -> Path:
    return CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".txt")


def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    body: dict | None = None,
    cache_hours: float = 12,
    timeout: float = 30,
) -> str:
    global _last_request
    key = f"{method} {url} {json.dumps(body, sort_keys=True) if body else ''}"
    cached = _cache_path(key)
    if cache_hours and cached.exists() and time.time() - cached.stat().st_mtime < cache_hours * 3600:
        return cached.read_text(encoding="utf-8")

    # Space out request *starts* (thread safe), so a few can be in flight at once.
    with _rate_lock:
        wait = MIN_INTERVAL_SECONDS - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
        "Accept-Encoding": "gzip",
    }
    req_headers.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            text = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise FetchError(f"{url} returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"{url} failed: {exc}") from exc

    if cache_hours:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_text(text, encoding="utf-8")
    return text


def fetch_with_browser(url: str, wait_ms: int = 4000) -> str:
    """Render a page in a real browser via Playwright (optional dependency).

    Some sites serve an anti-bot challenge to plain HTTP clients but will load
    normally in a browser. Install with ``pip install playwright`` then
    ``playwright install chromium``.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise FetchError("Playwright is not installed (pip install playwright)") from exc
    cached = _cache_path("BROWSER " + url)
    if cached.exists() and time.time() - cached.stat().st_mtime < 12 * 3600:
        return cached.read_text(encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=USER_AGENT, locale="en-AU")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(wait_ms)
            html = page.content()
        finally:
            browser.close()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(html, encoding="utf-8")
    time.sleep(MIN_INTERVAL_SECONDS)
    return html
