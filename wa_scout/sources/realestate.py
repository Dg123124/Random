"""realestate.com.au adapter (best effort, for personal use).

realestate.com.au has no public listings API and protects its site with bot
detection, so plain HTTP requests are often refused. This adapter tries a
normal request first, then a real browser via Playwright if installed. If both
are blocked, use the Domain API adapter, a CSV/JSON import, or let the Claude
Code agent gather listings with web search (see skills/wa-scout).

Please respect the site's terms of use: keep volumes low (the default is a few
pages, cached for 12 hours) and use this only for your own research.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from ..listings import Listing
from ..rent import weekly_rent_from_text
from .extract import listings_from_html
from .http import FetchError, fetch, fetch_with_browser

BASE = "https://www.realestate.com.au"
REA_TYPES = {
    "house": "house",
    "townhouse": "townhouse",
    "villa": "villa",
    "unit": "unit+apartment",
    "apartment": "unit+apartment",
    "duplex": "duplex-semi-detached",
    "land": "land",
}
METRO_REGION = "perth+-+greater+region,+wa"


def _location_slug(suburb: str | None, postcode: str | None) -> str:
    if not suburb:
        return METRO_REGION
    slug = quote_plus(suburb.strip().lower()) + ",+wa"
    if postcode:
        slug += f"+{postcode}"
    return slug


def search_url(criteria: dict, page: int = 1, channel: str = "buy", suburb: str | None = None,
               postcode: str | None = None, price_max: float | None = None) -> str:
    parts = []
    types = sorted({REA_TYPES[t] for t in criteria.get("property_types") or [] if t in REA_TYPES})
    if types:
        parts.append("property-" + "-".join(types))
    beds = criteria.get("bedrooms_min")
    if beds:
        parts.append(f"with-{int(beds)}-bedrooms")
    if channel == "buy":
        lo = int(criteria.get("price_min") or 0)
        hi = int(criteria.get("price_max") or price_max or 0)
        if hi:
            parts.append(f"between-{lo}-{hi}")
    parts.append("in-" + _location_slug(suburb, postcode))
    path = "-".join(parts)
    return f"{BASE}/{channel}/{path}/list-{page}?includeSurrounding=false&activeSort=list-date"


def _get_html(url: str, use_browser: bool) -> str:
    try:
        html = fetch(url)
        if "ArgonautExchange" in html:
            return html
    except FetchError:
        if not use_browser:
            raise
    if use_browser:
        return fetch_with_browser(url)
    raise FetchError(f"{url} did not return listing data (likely bot protection)")


def search(criteria: dict, max_pages: int = 5, price_max: float | None = None,
           use_browser: bool = True, log=print) -> list[Listing]:
    suburbs = [s for s in criteria.get("suburbs_include") or [] if s.strip()] or [None]
    results: list[Listing] = []
    for suburb in suburbs:
        for page in range(1, max_pages + 1):
            url = search_url(criteria, page, "buy", suburb, price_max=price_max)
            try:
                batch = listings_from_html(_get_html(url, use_browser))
            except FetchError as exc:
                log(f"[realestate.com.au] {exc}")
                return results
            log(f"[realestate.com.au] page {page}{' ' + suburb if suburb else ''}: {len(batch)} listings")
            if not batch:
                break
            results.extend(batch)
            if len(results) >= int(criteria.get("max_listings_to_scan") or 400):
                return results
    return results


def rental_comps(suburb: str, postcode: str | None, property_type: str, bedrooms: int | None,
                 use_browser: bool = True) -> list[Listing]:
    crit = {"property_types": [property_type], "bedrooms_min": bedrooms}
    url = search_url(crit, 1, "rent", suburb, postcode)
    comps = listings_from_html(_get_html(url, use_browser))  # raises FetchError when blocked
    for comp in comps:
        comp.price = weekly_rent_from_text(comp.price_text)
    return [c for c in comps if c.price]


def fetch_listing(url: str, use_browser: bool = True) -> Listing | None:
    """Parse a single listing page (e.g. a URL pasted into the web UI)."""
    listings = listings_from_html(_get_html(url, use_browser))
    for listing in listings:
        if listing.url and listing.url.rstrip("/") == url.rstrip("/"):
            return listing
    return listings[0] if listings else None
