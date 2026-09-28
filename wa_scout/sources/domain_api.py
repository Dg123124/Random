"""Domain Group official API adapter (the reliable, terms-compliant listing feed).

Create a free project at https://developer.domain.com.au, add the
"Listings Management" / "Agents & Listings" API with the free tier, and put the
API key in the DOMAIN_API_KEY environment variable (or in the web UI settings).
"""

from __future__ import annotations

import json
import os

from ..listings import Listing, parse_price
from .http import FetchError, fetch

SEARCH_URL = "https://api.domain.com.au/v1/listings/residential/_search"
DOMAIN_TYPES = {
    "house": ["House"],
    "townhouse": ["Townhouse"],
    "villa": ["Villa"],
    "unit": ["ApartmentUnitFlat"],
    "apartment": ["ApartmentUnitFlat"],
    "duplex": ["Duplex", "SemiDetached"],
    "land": ["VacantLand"],
}


def api_key() -> str | None:
    return os.environ.get("DOMAIN_API_KEY") or None


def _body(criteria: dict, listing_type: str, page: int, price_max: float | None, suburb: str | None) -> dict:
    types = sorted({t for pt in criteria.get("property_types") or [] for t in DOMAIN_TYPES.get(pt, [])})
    location = {"state": "WA", "region": "Perth Region" if not suburb else "", "suburb": suburb or "",
                "includeSurroundingSuburbs": False}
    body = {
        "listingType": listing_type,
        "propertyTypes": types or None,
        "minBedrooms": criteria.get("bedrooms_min") or None,
        "maxBedrooms": criteria.get("bedrooms_max") or None,
        "minBathrooms": criteria.get("bathrooms_min") or None,
        "minCarspaces": criteria.get("car_spaces_min") or None,
        "minLandArea": criteria.get("land_size_min_sqm") or None,
        "maxLandArea": criteria.get("land_size_max_sqm") or None,
        "locations": [location],
        "pageSize": 100,
        "pageNumber": page,
        "sort": {"sortKey": "DateListed", "direction": "Descending"},
    }
    if listing_type == "Sale":
        body["minPrice"] = criteria.get("price_min") or None
        body["maxPrice"] = criteria.get("price_max") or price_max or None
    return {k: v for k, v in body.items() if v is not None}


def _to_listing(item: dict, rent: bool = False) -> Listing | None:
    listing = item.get("listing") or item
    details = listing.get("propertyDetails") or {}
    price_details = listing.get("priceDetails") or {}
    if not details:
        return None
    price_text = price_details.get("displayPrice", "")
    price = price_details.get("price") or price_details.get("priceFrom")
    if not rent and not price:
        price = parse_price(price_text)
    slug = listing.get("listingSlug", "")
    types = details.get("allPropertyTypes") or [details.get("propertyType", "")]
    return Listing.from_dict(
        {
            "id": f"domain-{listing.get('id')}",
            "url": f"https://www.domain.com.au/{slug}" if slug else "",
            "address": details.get("displayableAddress", ""),
            "suburb": details.get("suburb", ""),
            "postcode": details.get("postcode", ""),
            "state": details.get("state", "WA"),
            "property_type": types[0] if types else "",
            "price_text": price_text,
            "price": price,
            "bedrooms": details.get("bedrooms"),
            "bathrooms": details.get("bathrooms"),
            "car_spaces": details.get("carspaces"),
            "land_size_sqm": details.get("landArea"),
            "building_size_sqm": details.get("buildingArea"),
            "listed_date": listing.get("dateListed", ""),
            "headline": listing.get("headline", ""),
            "source": "domain-api",
            "extra": {"description": (listing.get("summaryDescription") or "")[:3000]},
        }
    )


def search(criteria: dict, price_max: float | None = None, max_pages: int = 5, log=print, key: str | None = None) -> list[Listing]:
    key = key or api_key()
    if not key:
        log("[domain] no DOMAIN_API_KEY set, skipping")
        return []
    suburbs = [s for s in criteria.get("suburbs_include") or [] if s.strip()] or [None]
    out: list[Listing] = []
    for suburb in suburbs:
        for page in range(1, max_pages + 1):
            try:
                raw = fetch(SEARCH_URL, method="POST", headers={"X-Api-Key": key},
                            body=_body(criteria, "Sale", page, price_max, suburb))
            except FetchError as exc:
                log(f"[domain] {exc}")
                return out
            items = json.loads(raw)
            batch = [l for l in (_to_listing(i) for i in items if i.get("type", "PropertyListing") == "PropertyListing") if l]
            log(f"[domain] page {page}{' ' + suburb if suburb else ''}: {len(batch)} listings")
            out.extend(batch)
            if len(items) < 100:
                break
    return out


def rental_comps(suburb: str, property_type: str, bedrooms: int | None, key: str | None = None, log=print) -> list[Listing]:
    key = key or api_key()
    if not key:
        return []
    crit = {"property_types": [property_type], "bedrooms_min": bedrooms, "bedrooms_max": bedrooms}
    try:
        raw = fetch(SEARCH_URL, method="POST", headers={"X-Api-Key": key}, body=_body(crit, "Rent", 1, None, suburb))
    except FetchError as exc:
        log(f"[domain rent] {exc}")
        return []
    from ..rent import weekly_rent_from_text

    comps = []
    for item in json.loads(raw):
        listing = _to_listing(item, rent=True)
        if listing:
            listing.price = weekly_rent_from_text(listing.price_text) or listing.price
            if listing.price and listing.price < 5000:
                comps.append(listing)
    return comps
