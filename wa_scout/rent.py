"""Rental income forecasting from freely available data.

Estimates come from the best source available, in this order:

1. The listing itself says it is leased ("currently leased at $620 pw").
2. Comparable rental listings in the same suburb (``data/rental_comps.json``),
   collected by the source adapters or the Claude Code agent.
3. Suburb median rent (``data/suburb_stats.csv``), e.g. from REIWA, SQM
   Research or realestate.com.au suburb profiles.
4. Perth metro medians (``data/perth_baseline.json``), scaled by bedrooms
   and price. This is the low-confidence fallback.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR
from .finance import is_unit_like
from .listings import Listing


@dataclass
class RentEstimate:
    weekly: float
    low: float
    high: float
    method: str
    confidence: float  # 0..1
    notes: str = ""

    def __post_init__(self):
        self.weekly, self.low, self.high = round(self.weekly), round(self.low), round(self.high)

    def to_dict(self) -> dict:
        return asdict(self)


def rent_class(property_type: str) -> str:
    return "unit" if is_unit_like(property_type) else "house"


@lru_cache(maxsize=4)
def load_baseline(path: str | None = None) -> dict:
    with open(path or DATA_DIR / "perth_baseline.json", encoding="utf-8") as fh:
        return json.load(fh)


def load_suburb_stats(path: Path | str | None = None) -> dict[tuple[str, str], dict]:
    """Map (suburb_lower, house|unit) -> row."""
    path = Path(path or DATA_DIR / "suburb_stats.csv")
    stats: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return stats
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(line for line in fh if not line.startswith("#")):
            suburb = (row.get("suburb") or "").strip().lower()
            if not suburb:
                continue
            cls = rent_class(row.get("property_type") or "house")
            stats[(suburb, cls)] = row
    return stats


def load_comps(path: Path | str | None = None) -> list[Listing]:
    path = Path(path or DATA_DIR / "rental_comps.json")
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    comps = []
    for item in raw.get("listings", raw) if isinstance(raw, dict) else raw:
        listing = Listing.from_dict(item)
        # Rental comps store weekly rent in ``price`` (parsed from "$650 per week").
        rent = item.get("weekly_rent") or weekly_rent_from_text(item.get("price_text", ""))
        if not rent and isinstance(item.get("price"), (int, float)) and 100 <= item["price"] <= 5000:
            rent = item["price"]
        if rent:
            listing.price = float(rent)
            comps.append(listing)
    return comps


_LEASED = re.compile(
    r"(?:leased|rented|tenanted|returning|rent(?:al)? (?:of|at)|income of)[^$]{0,40}\$\s?(\d{3,4})(?:\.\d+)?\s*(?:p/?w|per ?week|pw|/ ?w(?:ee)?k|a week|weekly)",
    re.I,
)


def weekly_rent_from_text(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"\$\s?(\d{3,4})(?:\.\d+)?\s*(?:p/?w|per ?week|pw|/ ?w(?:ee)?k|weekly|a week)?", text, re.I)
    if not m:
        return None
    value = float(m.group(1))
    return value if 100 <= value <= 5000 else None


def stated_rent(listing: Listing) -> float | None:
    text = " ".join(
        str(x) for x in (listing.headline, listing.extra.get("description", ""), listing.extra.get("rent_text", "")) if x
    )
    m = _LEASED.search(text)
    if m:
        value = float(m.group(1))
        if 150 <= value <= 5000:
            return value
    if listing.extra.get("current_weekly_rent"):
        return float(listing.extra["current_weekly_rent"])
    return None


def _bedroom_factor(baseline: dict, cls: str, bedrooms: int | None) -> float:
    table = baseline["bedroom_multipliers"][cls]
    if bedrooms is None:
        return 1.0
    key = str(max(min(bedrooms, int(max(table, key=int))), int(min(table, key=int))))
    return float(table[key])


def _feature_factor(listing: Listing, cls: str) -> float:
    factor = 1.0
    if cls == "house":
        if listing.bathrooms and listing.bathrooms >= 2:
            factor += 0.03 * min(listing.bathrooms - 1, 2)
        if listing.car_spaces == 0:
            factor -= 0.03
    else:
        if listing.car_spaces == 0:
            factor -= 0.05
        if listing.bathrooms and listing.bathrooms >= 2:
            factor += 0.03
    return factor


def estimate_rent(
    listing: Listing,
    suburb_stats: dict | None = None,
    comps: list[Listing] | None = None,
    baseline: dict | None = None,
) -> RentEstimate:
    baseline = baseline or load_baseline()
    suburb_stats = load_suburb_stats() if suburb_stats is None else suburb_stats
    comps = load_comps() if comps is None else comps
    cls = rent_class(listing.property_type)
    beds = listing.bedrooms

    stated = stated_rent(listing)
    if stated:
        return RentEstimate(stated, stated * 0.97, stated * 1.03, "stated in listing", 0.95,
                            "Listing advertises current/achievable rent; verify the lease.")

    # Comparable rental listings: same suburb and class, same bedroom count first.
    suburb = listing.suburb.lower()
    local = [c for c in comps if c.suburb.lower() == suburb and rent_class(c.property_type) == cls and c.price]
    exact = [c.price for c in local if beds is None or c.bedrooms == beds]
    if len(exact) >= 3:
        med = statistics.median(exact)
        q = _spread(exact)
        conf = min(0.9, 0.6 + 0.04 * len(exact))
        return RentEstimate(round(med), q[0], q[1], f"{len(exact)} comparable rentals in {listing.suburb}", conf)
    near = [
        c.price * _bedroom_factor(baseline, cls, beds) / _bedroom_factor(baseline, cls, c.bedrooms)
        for c in local
        if beds is None or c.bedrooms is None or abs(c.bedrooms - beds) <= 1
    ]
    if len(near) >= 3:
        med = statistics.median(near)
        q = _spread(near)
        return RentEstimate(round(med), q[0], q[1],
                            f"{len(near)} nearby-size rentals in {listing.suburb} (bedroom-adjusted)", 0.65)

    # Suburb median rent from public market data.
    row = suburb_stats.get((suburb, cls))
    if row and row.get("median_weekly_rent"):
        med = float(row["median_weekly_rent"])
        typical_beds = baseline["typical_bedrooms"][cls]
        adj = _bedroom_factor(baseline, cls, beds) / _bedroom_factor(baseline, cls, typical_beds)
        weekly = round(med * adj * _feature_factor(listing, cls))
        return RentEstimate(weekly, weekly * 0.9, weekly * 1.1,
                            f"{listing.suburb} median rent ({row.get('source', 'public data')}, {row.get('as_of', 'n/a')})",
                            0.55, "Suburb median adjusted for bedrooms and features.")

    # Perth-wide fallback, scaled by bedrooms and by price relative to the metro median.
    metro = baseline["metro"][cls]
    base = float(metro["median_weekly_rent"]) * _bedroom_factor(baseline, cls, beds) / _bedroom_factor(
        baseline, cls, baseline["typical_bedrooms"][cls]
    )
    if listing.price:
        base *= (listing.price / float(metro["median_price"])) ** float(baseline["price_elasticity"])
    weekly = round(base * _feature_factor(listing, cls))
    return RentEstimate(weekly, weekly * 0.85, weekly * 1.15,
                        f"Perth metro median ({baseline['source']}, {baseline['as_of']}) scaled by beds and price",
                        0.3, "Low confidence. Run the refresh-rents skill or add suburb data to improve this.")


def _spread(values: list[float]) -> tuple[float, float]:
    values = sorted(values)
    if len(values) < 4:
        return values[0], values[-1]
    q = statistics.quantiles(values, n=4)
    return q[0], q[2]


def suburb_median_price(listing: Listing, suburb_stats: dict | None = None) -> float | None:
    suburb_stats = load_suburb_stats() if suburb_stats is None else suburb_stats
    row = suburb_stats.get((listing.suburb.lower(), rent_class(listing.property_type)))
    if row and row.get("median_price"):
        try:
            return float(row["median_price"])
        except ValueError:
            return None
    return None
