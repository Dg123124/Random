"""Listing model, price parsing and criteria filtering."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields

TYPE_ALIASES = {
    "house": "house",
    "home": "house",
    "residential": "house",
    "acreage": "house",
    "semi-detached": "duplex",
    "semi": "duplex",
    "duplex": "duplex",
    "duplex-semi-detached": "duplex",
    "townhouse": "townhouse",
    "terrace": "townhouse",
    "villa": "villa",
    "unit": "unit",
    "flat": "unit",
    "apartment": "apartment",
    "apartmentunitflat": "apartment",
    "unitblock": "unit",
    "studio": "apartment",
    "land": "land",
    "vacantland": "land",
}


def normalise_type(raw: str | None) -> str:
    if not raw:
        return "house"
    key = re.sub(r"[^a-z-]", "", raw.lower().replace(" ", ""))
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    for alias, canonical in TYPE_ALIASES.items():
        if alias in key:
            return canonical
    return key or "house"


@dataclass
class Listing:
    id: str
    url: str = ""
    address: str = ""
    suburb: str = ""
    postcode: str = ""
    state: str = "WA"
    property_type: str = "house"
    price_text: str = ""
    price: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    car_spaces: int | None = None
    land_size_sqm: float | None = None
    building_size_sqm: float | None = None
    strata_annual: float | None = None
    council_annual: float | None = None
    listed_date: str = ""
    days_on_market: int | None = None
    agent: str = ""
    headline: str = ""
    source: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Listing":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        listing = cls(**clean)
        listing.property_type = normalise_type(listing.property_type)
        if listing.price is None and listing.price_text:
            listing.price = parse_price(listing.price_text)
        for attr in ("bedrooms", "bathrooms", "car_spaces", "days_on_market"):
            val = getattr(listing, attr)
            if val not in (None, ""):
                try:
                    setattr(listing, attr, int(float(val)))
                except (TypeError, ValueError):
                    setattr(listing, attr, None)
        for attr in ("price", "land_size_sqm", "building_size_sqm", "strata_annual", "council_annual"):
            val = getattr(listing, attr)
            if isinstance(val, str):
                setattr(listing, attr, parse_number(val))
        listing.suburb = (listing.suburb or "").strip().title()
        listing.postcode = str(listing.postcode or "").strip()
        return listing


_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:[,\s]\d{3})+|\d+(?:\.\d+)?)\s*(k|m|mil|million|thousand)?\b", re.I)


def parse_number(text) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text))
    return float(m.group(0).replace(",", "")) if m else None


def _money_values(text: str) -> list[float]:
    values = []
    for number, suffix in _MONEY.findall(text):
        value = float(re.sub(r"[,\s]", "", number))
        suffix = (suffix or "").lower()
        if suffix == "k" or suffix == "thousand":
            value *= 1_000
        elif suffix in {"m", "mil", "million"}:
            value *= 1_000_000
        if value >= 50_000:  # ignore bedroom counts, years, weekly rents, etc.
            values.append(value)
    return values


def parse_price(text: str | None) -> float | None:
    """Turn Australian listing price text into a single estimate.

    "Offers over $650,000" -> 650000, "$600k - $640k" -> 620000,
    "From $1.2m" -> 1200000, "Contact agent" -> None.
    """
    if not text:
        return None
    values = _money_values(str(text))
    if not values:
        return None
    if len(values) >= 2:
        return round((values[0] + values[1]) / 2, 0)
    return values[0]


def parse_area(text) -> float | None:
    """Parse "650m²", "650 sqm", "0.2 ha", "1 acre" into square metres."""
    if text is None or text == "":
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).lower().replace(",", "")
    num = parse_number(s)
    if num is None:
        return None
    if "ha" in s or "hectare" in s:
        return num * 10_000
    if "acre" in s:
        return num * 4_046.86
    return num


def in_metro(listing: Listing, criteria: dict) -> bool:
    if (listing.state or "WA").upper() != "WA":
        return False
    try:
        pc = int(listing.postcode)
    except (TypeError, ValueError):
        return True  # unknown postcode: keep it and let the user decide
    return any(lo <= pc <= hi for lo, hi in criteria.get("metro_postcodes", [[6000, 6199]]))


def matches_criteria(listing: Listing, criteria: dict, price_cap: float | None = None) -> tuple[bool, list[str]]:
    """Return (matches, reasons_it_failed)."""
    reasons: list[str] = []
    types = [t.lower() for t in criteria.get("property_types") or []]
    if types and listing.property_type not in types:
        reasons.append(f"type {listing.property_type} not in {types}")
    if not in_metro(listing, criteria):
        reasons.append("outside metropolitan WA")

    include = {s.strip().lower() for s in criteria.get("suburbs_include") or [] if s.strip()}
    exclude = {s.strip().lower() for s in criteria.get("suburbs_exclude") or [] if s.strip()}
    if include and listing.suburb.lower() not in include:
        reasons.append("suburb not in include list")
    if listing.suburb.lower() in exclude:
        reasons.append("suburb excluded")

    def check_min(value, minimum, label):
        if minimum and value is not None and value < minimum:
            reasons.append(f"{label} {value} < {minimum}")

    def check_max(value, maximum, label):
        if maximum and value is not None and value > maximum:
            reasons.append(f"{label} {value} > {maximum}")

    check_min(listing.bedrooms, criteria.get("bedrooms_min"), "bedrooms")
    check_max(listing.bedrooms, criteria.get("bedrooms_max"), "bedrooms")
    check_min(listing.bathrooms, criteria.get("bathrooms_min"), "bathrooms")
    check_min(listing.car_spaces, criteria.get("car_spaces_min"), "car spaces")
    check_min(listing.land_size_sqm, criteria.get("land_size_min_sqm"), "land m²")
    if criteria.get("land_size_min_sqm") and listing.land_size_sqm is None:
        reasons.append("land size unknown")
    check_max(listing.land_size_sqm, criteria.get("land_size_max_sqm"), "land m²")
    check_min(listing.building_size_sqm, criteria.get("building_size_min_sqm"), "building m²")

    km = listing.extra.get("km_to_cbd")
    if criteria.get("max_km_to_cbd") and km is not None and km > criteria["max_km_to_cbd"]:
        reasons.append(f"distance {km} km > {criteria['max_km_to_cbd']} km")
    if listing.extra.get("status") in {"sold", "under offer"}:
        reasons.append(f"status {listing.extra['status']}")

    if listing.price is not None:
        check_min(listing.price, criteria.get("price_min"), "price")
        cap = criteria.get("price_max") or price_cap
        check_max(listing.price, cap, "price")
    return (not reasons, reasons)


def dedupe(listings: list[Listing]) -> list[Listing]:
    """Merge the same property seen from several sources (by normalised address)."""
    seen: dict[str, Listing] = {}
    for listing in listings:
        key = re.sub(r"[^a-z0-9]", "", f"{listing.address}{listing.suburb}".lower()) or listing.id
        existing = seen.get(key)
        if existing is None:
            seen[key] = listing
            continue
        for f in fields(Listing):
            if getattr(existing, f.name) in (None, "", {}) and getattr(listing, f.name) not in (None, "", {}):
                setattr(existing, f.name, getattr(listing, f.name))
    return list(seen.values())
