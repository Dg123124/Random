"""REIWA (reiwa.com.au) adapter: WA's own listing portal, server-rendered HTML.

Search pages list 20 listings each with price text, beds, baths, cars and type.
Detail pages add land size, floor area and the description (used to spot
"currently leased at $X pw"). Rental search pages give comparable rents.

Requests are rate limited and cached (see ``http.py``). Keep volumes modest and
use it for personal research only.
"""

from __future__ import annotations

import html as htmllib
import re

from ..listings import Listing, parse_area
from .http import FetchError, fetch

BASE = "https://reiwa.com.au"
_CARD = re.compile(r'<article class="p-card.*?</article>', re.S)
_HREF = re.compile(r'href="(/[a-z0-9-]+-(\d{7})/)"')
_PRICE = re.compile(r'<p class="heading h4[^"]*">(.*?)</p>', re.S)
_ADDR = re.compile(r'<h2 class="[^"]*p-details__add[^"]*">(.*?)</h2>', re.S)
_FEATURES = re.compile(r'<span class="u-grey-dark">(\d+)</span>')
_TYPE = re.compile(r'<div class="grey-pill[^"]*">(.*?)</div>')
_ADDED = re.compile(r"Added (\d+|a) (day|days|week|weeks|month|months) ago")
_ICON = re.compile(r'class="icon -left -(bed|bath|car)"')


def slug(suburb: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", suburb.lower()).strip("-")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _days(card_text: str) -> int | None:
    m = _ADDED.search(card_text)
    if not m:
        return None
    n = 1 if m.group(1) == "a" else int(m.group(1))
    unit = m.group(2)
    return n * (30 if unit.startswith("month") else 7 if unit.startswith("week") else 1)


def parse_cards(page: str, default_postcode: str = "") -> list[Listing]:
    out = []
    for card in _CARD.findall(page):
        card = re.sub(r"<svg.*?</svg>", "", card, flags=re.S)
        href = _HREF.search(card)
        addr = _ADDR.search(card)
        if not href or not addr:
            continue
        address_full = _text(addr.group(1))
        street, _, suburb = address_full.rpartition(",")
        price_m = _PRICE.search(card)
        feats = [int(x) for x in _FEATURES.findall(card)]
        # Cards list bed, bath, car in that order; a missing icon shifts the rest.
        icons = _ICON.findall(card) or ["bed", "bath", "car"][: len(feats)]
        values = dict(zip(icons, feats))
        ptypes = [_text(t) for t in _TYPE.findall(card)]
        ptypes = [t for t in ptypes if t.lower() not in {"new", "under offer", "sold"}]
        text = _text(card)
        out.append(Listing.from_dict({
            "id": f"reiwa-{href.group(2)}",
            "url": BASE + href.group(1),
            "address": street.strip() or address_full,
            "suburb": suburb.strip(),
            "postcode": default_postcode,
            "property_type": ptypes[-1] if ptypes else "house",
            "price_text": _text(price_m.group(1)) if price_m else "",
            "bedrooms": values.get("bed"),
            "bathrooms": values.get("bath"),
            "car_spaces": values.get("car"),
            "days_on_market": _days(text),
            "source": "reiwa.com.au",
            "extra": {"status": "under offer" if "under offer" in text.lower() else ""},
        }))
    return out


def search_url(suburb: str, page: int = 1, channel: str = "for-sale", kind: str = "houses") -> str:
    url = f"{BASE}/{channel}/{slug(suburb)}/{kind}/"
    return url + (f"?page={page}" if page > 1 else "")


def search_suburb(suburb: str, max_pages: int = 3, log=print) -> list[Listing]:
    results: list[Listing] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        try:
            batch = parse_cards(fetch(search_url(suburb, page)))
        except FetchError as exc:
            log(f"[reiwa] {suburb} page {page}: {exc}")
            break
        new = [l for l in batch if l.id not in seen]
        seen.update(l.id for l in new)
        results.extend(new)
        if len(batch) < 20 or not new:
            break
    # Search pages can include featured listings from neighbouring suburbs; keep them, they are real.
    log(f"[reiwa] {suburb}: {len(results)} listings")
    return results


PERTH_CBD = (-31.9523, 115.8613)


def distance_km(lat: float, lon: float, origin=PERTH_CBD) -> float:
    """Straight-line distance in km (haversine)."""
    import math

    r = 6371.0
    p1, p2 = math.radians(origin[0]), math.radians(lat)
    dphi, dl = p2 - p1, math.radians(lon - origin[1])
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def listing_data(page: str) -> dict:
    """The JSON REIWA embeds in the listing page (data-props on the action buttons)."""
    import json

    for m in re.finditer(r"data-props='([^']*ListingNo[^']*)'", page):
        try:
            return json.loads(htmllib.unescape(m.group(1))).get("data", {})
        except json.JSONDecodeError:
            continue
    return {}


def enrich(listing: Listing) -> Listing:
    """Fetch the detail page for land size, postcode, location, status and the ad text."""
    page = fetch(listing.url, cache_hours=24)
    d = listing_data(page)
    if d:
        land = re.match(r"([\d,.]+)\s*(m|ha)", d.get("LandsizeHtml") or "")
        if land:
            listing.land_size_sqm = parse_area(f"{land.group(1)} {'ha' if land.group(2) == 'ha' else 'm2'}")
        loc = d.get("ListingLocation") or {}
        listing.postcode = loc.get("Postcode") or listing.postcode
        listing.suburb = loc.get("Suburb") or listing.suburb
        if loc.get("GeoLatitude") and loc.get("GeoLongitude"):
            listing.extra["lat"], listing.extra["lon"] = loc["GeoLatitude"], loc["GeoLongitude"]
            listing.extra["km_to_cbd"] = round(distance_km(loc["GeoLatitude"], loc["GeoLongitude"]), 1)
        listing.bedrooms = d.get("Beds", listing.bedrooms)
        listing.bathrooms = d.get("Baths", listing.bathrooms)
        listing.car_spaces = d.get("Cars", listing.car_spaces)
        listing.price_text = d.get("DisplayPrice") or listing.price_text
        listing.headline = d.get("Headline") or listing.headline
        listing.listed_date = (d.get("ListDate") or "")[:10]
        listing.extra["description"] = _text(d.get("Description") or "")[:3000]
        listing.extra["status"] = "sold" if d.get("IsSold") else "under offer" if d.get("IsUnderOffer") else ""
        listing.extra["features"] = [f.get("Line1Text") for f in d.get("Features") or []]
        stats = d.get("SuburbStatistics") or {}
        if stats.get("StatsAvailable"):
            listing.extra["suburb_stats"] = {
                "median_price": stats.get("SalePriceMedianValue"),
                "median_rent": stats.get("MedianRentValue"),
                "annual_growth": stats.get("AnnualGrowthValue"),
                "avg_days_on_market": stats.get("AverageDaysOnMarket"),
            }
        if listing.listed_date and listing.days_on_market is None:
            import datetime as dt

            try:
                listed = dt.date.fromisoformat(listing.listed_date)
                listing.days_on_market = (dt.date.today() - listed).days
            except ValueError:
                pass
    else:
        land = re.search(r"Landsize\s*<strong>([\d,.]+)\s*(m|ha)", page)
        if land:
            listing.land_size_sqm = parse_area(f"{land.group(1)} {'ha' if land.group(2) == 'ha' else 'm2'}")
    return listing


def rental_comps(suburb: str, max_pages: int = 2, log=print) -> list[Listing]:
    """Current rental listings (houses) in a suburb, with weekly rent in ``price``."""
    from ..rent import weekly_rent_from_text

    comps: list[Listing] = []
    for page in range(1, max_pages + 1):
        try:
            batch = parse_cards(fetch(search_url(suburb, page, channel="rental-properties")))
        except FetchError as exc:
            log(f"[reiwa rent] {suburb}: {exc}")
            break
        for comp in batch:
            comp.price = weekly_rent_from_text(comp.price_text)
            if comp.price:
                comps.append(comp)
        if len(batch) < 20:
            break
    return comps
