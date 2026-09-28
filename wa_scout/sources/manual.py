"""Import listings you collected yourself (CSV or JSON), e.g. from a saved search."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..listings import Listing

CSV_COLUMNS = [
    "address", "suburb", "postcode", "property_type", "price_text", "price", "bedrooms", "bathrooms",
    "car_spaces", "land_size_sqm", "building_size_sqm", "strata_annual", "council_annual",
    "days_on_market", "url", "headline",
]


def load_file(path: str | Path) -> list[Listing]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        items = raw.get("listings", []) if isinstance(raw, dict) else raw
    else:
        with open(path, encoding="utf-8-sig") as fh:
            items = [{k: v for k, v in row.items() if v not in (None, "")} for row in csv.DictReader(fh)]
    out = []
    for i, item in enumerate(items):
        item.setdefault("id", f"manual-{path.stem}-{i}")
        item.setdefault("source", "manual")
        extra = item.setdefault("extra", {})
        if item.get("description"):
            extra["description"] = item["description"]
        if item.get("current_weekly_rent"):
            extra["current_weekly_rent"] = item["current_weekly_rent"]
        out.append(Listing.from_dict(item))
    return out
