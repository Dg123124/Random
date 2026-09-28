"""Pull listing records out of the JSON that property portals embed in their HTML.

realestate.com.au ships search results inside ``window.ArgonautExchange`` (with
JSON nested as strings), Domain uses ``__NEXT_DATA__``, and many agency sites
use JSON-LD. Rather than hard-coding one fragile path, we decode every embedded
JSON blob, walk it, and map anything that looks like a listing.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from typing import Iterator

from ..listings import Listing, parse_area, parse_price

_SCRIPT_JSON = [
    re.compile(r"window\.ArgonautExchange\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S),
    re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S),
    re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S),
    re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S),
]


def embedded_json(html: str) -> list:
    blobs = []
    for pattern in _SCRIPT_JSON:
        for match in pattern.finditer(html):
            try:
                blobs.append(json.loads(htmllib.unescape(match.group(1)) if "&quot;" in match.group(1) else match.group(1)))
            except json.JSONDecodeError:
                continue
    return blobs


def _walk(node, depth: int = 0) -> Iterator[dict]:
    if depth > 40:
        return
    if isinstance(node, str):
        s = node.strip()
        if len(s) > 20 and s[0] in "{[":
            try:
                yield from _walk(json.loads(s), depth + 1)
            except json.JSONDecodeError:
                pass
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, depth + 1)


def _get(d, *path, default=None):
    for key in path:
        if isinstance(d, dict):
            d = d.get(key)
        elif isinstance(d, list) and isinstance(key, int) and len(d) > key:
            d = d[key]
        else:
            return default
    return default if d is None else d


def _abs_url(href: str, base: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return base.rstrip("/") + "/" + href.lstrip("/")


def _from_rea(d: dict) -> Listing | None:
    addr = d.get("address")
    features = d.get("generalFeatures")
    if not isinstance(addr, dict) or not (features or d.get("price")):
        return None
    if not (addr.get("suburb") or _get(addr, "display", "shortAddress")):
        return None
    land = _get(d, "propertySizes", "land")
    building = _get(d, "propertySizes", "building")

    def size(obj):
        if not isinstance(obj, dict):
            return None
        return parse_area(f"{obj.get('displayValue', '')} {_get(obj, 'sizeUnit', 'displayValue', default='')}")

    href = _get(d, "_links", "canonical", "href") or _get(d, "_links", "canonical", "path") or ""
    return Listing.from_dict(
        {
            "id": f"rea-{d.get('id') or href}",
            "url": _abs_url(href, "https://www.realestate.com.au"),
            "address": _get(addr, "display", "shortAddress") or _get(addr, "display", "fullAddress") or addr.get("streetAddress", ""),
            "suburb": addr.get("suburb", ""),
            "postcode": addr.get("postcode", ""),
            "state": (addr.get("state") or "WA").upper(),
            "property_type": _get(d, "propertyType", "id") or _get(d, "propertyType", "display") or "",
            "price_text": _get(d, "price", "display") or "",
            "bedrooms": _get(features or {}, "bedrooms", "value"),
            "bathrooms": _get(features or {}, "bathrooms", "value"),
            "car_spaces": _get(features or {}, "parkingSpaces", "value"),
            "land_size_sqm": size(land),
            "building_size_sqm": size(building),
            "listed_date": _get(d, "dateListed", "value") or _get(d, "listingDate") or "",
            "agent": _get(d, "listingCompany", "name") or "",
            "headline": d.get("title") or d.get("headline") or "",
            "source": "realestate.com.au",
            "extra": {"description": (d.get("description") or "")[:3000]},
        }
    )


def _from_domain(d: dict) -> Listing | None:
    model = d.get("listingModel") if isinstance(d.get("listingModel"), dict) else None
    if not model:
        return None
    addr = model.get("address") or {}
    feats = model.get("features") or {}
    return Listing.from_dict(
        {
            "id": f"domain-{d.get('id') or model.get('url')}",
            "url": _abs_url(model.get("url", ""), "https://www.domain.com.au"),
            "address": addr.get("street", ""),
            "suburb": addr.get("suburb", ""),
            "postcode": addr.get("postcode", ""),
            "state": (addr.get("state") or "WA").upper(),
            "property_type": feats.get("propertyTypeFormatted") or feats.get("propertyType") or "",
            "price_text": model.get("price", ""),
            "bedrooms": feats.get("beds"),
            "bathrooms": feats.get("baths"),
            "car_spaces": feats.get("parking"),
            "land_size_sqm": parse_area(f"{feats.get('landSize', '')} {feats.get('landUnit', '')}") if feats.get("landSize") else None,
            "headline": model.get("promoType", ""),
            "source": "domain.com.au",
        }
    )


def _from_jsonld(d: dict) -> Listing | None:
    kind = d.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    if not any(k in {"SingleFamilyResidence", "House", "Residence", "Apartment", "RealEstateListing", "Accommodation"} for k in kinds):
        return None
    addr = d.get("address") if isinstance(d.get("address"), dict) else _get(d, "mainEntity", "address") or {}
    if not addr:
        return None
    offer = d.get("offers") if isinstance(d.get("offers"), dict) else {}
    return Listing.from_dict(
        {
            "id": f"jsonld-{d.get('url') or addr.get('streetAddress')}",
            "url": d.get("url", ""),
            "address": addr.get("streetAddress", ""),
            "suburb": addr.get("addressLocality", ""),
            "postcode": addr.get("postalCode", ""),
            "state": (addr.get("addressRegion") or "WA").upper(),
            "property_type": kinds[0] if kinds[0] != "RealEstateListing" else "house",
            "price": parse_price(str(offer.get("price", ""))) if offer else None,
            "bedrooms": d.get("numberOfRooms") or d.get("numberOfBedrooms"),
            "bathrooms": d.get("numberOfBathroomsTotal"),
            "land_size_sqm": parse_area(_get(d, "floorSize", "value")),
            "headline": d.get("name", ""),
            "source": "json-ld",
        }
    )


def listings_from_html(html: str) -> list[Listing]:
    found: dict[str, Listing] = {}
    for blob in embedded_json(html):
        for node in _walk(blob):
            for mapper in (_from_rea, _from_domain, _from_jsonld):
                try:
                    listing = mapper(node)
                except (TypeError, ValueError, AttributeError):
                    listing = None
                if listing and listing.suburb:
                    existing = found.get(listing.id)
                    # Keep the richest version when the same listing appears twice.
                    if existing is None or len(json.dumps(listing.to_dict())) > len(json.dumps(existing.to_dict())):
                        found[listing.id] = listing
                    break
    return list(found.values())
