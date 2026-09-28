"""The scouting pipeline: gather listings -> refresh rent data -> score -> top 20 report."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import finance, report
from .config import DATA_DIR, REPORTS_DIR, load_profile
from .listings import Listing, dedupe, matches_criteria
from .rent import rent_class
from .scoring import rank_listings
from .sources import domain_api, manual, realestate
from .sources.http import FetchError

INBOX_DIR = DATA_DIR / "inbox"
LISTINGS_PATH = DATA_DIR / "listings.json"
COMPS_PATH = DATA_DIR / "rental_comps.json"
ALL_SOURCES = ("inbox", "domain", "realestate")


def load_inbox(log=print) -> list[Listing]:
    """Listings dropped into data/inbox/ by you or by the Claude Code agent."""
    out: list[Listing] = []
    if not INBOX_DIR.exists():
        return out
    for path in sorted(INBOX_DIR.glob("*")):
        if path.suffix.lower() in {".json", ".csv"}:
            batch = manual.load_file(path)
            log(f"[inbox] {path.name}: {len(batch)} listings")
            out.extend(batch)
    return out


def gather(profile: dict, sources=ALL_SOURCES, pages: int = 5, use_browser: bool = True, log=print) -> list[Listing]:
    crit = profile["criteria"]
    price_max = crit.get("price_max") or finance.max_purchase_price(profile)
    found: list[Listing] = []
    if "inbox" in sources:
        found += load_inbox(log)
    if "domain" in sources:
        found += domain_api.search(crit, price_max=price_max, max_pages=pages, log=log)
    if "realestate" in sources:
        found += realestate.search(crit, max_pages=pages, price_max=price_max, use_browser=use_browser, log=log)
    listings = dedupe(found)
    if not listings and LISTINGS_PATH.exists():
        log("No listings gathered this run; re-using the previously saved listings")
        return load_saved_listings()
    LISTINGS_PATH.write_text(
        json.dumps({"updated": dt.datetime.now().isoformat(timespec="seconds"),
                    "listings": [l.to_dict() for l in listings]}, indent=1),
        encoding="utf-8",
    )
    log(f"Gathered {len(listings)} unique listings")
    return listings


def load_saved_listings() -> list[Listing]:
    if not LISTINGS_PATH.exists():
        return []
    raw = json.loads(LISTINGS_PATH.read_text(encoding="utf-8"))
    return [Listing.from_dict(d) for d in raw.get("listings", [])]


def refresh_rental_comps(listings: list[Listing], profile: dict, max_suburbs: int = 15,
                         use_browser: bool = True, log=print) -> int:
    """Collect current rental listings for the suburbs that matter most (cheap, cached)."""
    crit = profile["criteria"]
    cap = crit.get("price_max") or finance.max_purchase_price(profile)
    wanted: dict[tuple[str, str], Listing] = {}
    for listing in listings:
        if matches_criteria(listing, crit, cap)[0]:
            wanted.setdefault((listing.suburb, rent_class(listing.property_type)), listing)
    existing = json.loads(COMPS_PATH.read_text(encoding="utf-8")) if COMPS_PATH.exists() else {"listings": []}
    comps = {c.get("id"): c for c in existing.get("listings", [])}
    added = 0
    rea_blocked = False
    for (suburb, cls), sample in list(wanted.items())[:max_suburbs]:
        batch = domain_api.rental_comps(suburb, sample.property_type, sample.bedrooms, log=log)
        if not batch and not rea_blocked:
            try:
                batch = realestate.rental_comps(suburb, sample.postcode, sample.property_type, sample.bedrooms,
                                                use_browser=use_browser)
            except FetchError as exc:
                log(f"[realestate.com.au rent] {exc}; skipping remaining suburbs")
                rea_blocked = True
        for comp in batch:
            d = comp.to_dict()
            d["weekly_rent"] = comp.price
            d["collected"] = dt.date.today().isoformat()
            if d["id"] not in comps:
                added += 1
            comps[d["id"]] = d
        log(f"[rent comps] {suburb} {cls}: {len(batch)} rentals")
    COMPS_PATH.write_text(json.dumps({"updated": dt.date.today().isoformat(), "listings": list(comps.values())}, indent=1),
                          encoding="utf-8")
    return added


def run(profile: dict | None = None, sources=ALL_SOURCES, pages: int = 5, use_browser: bool = True,
        refresh_rents: bool = True, fetch: bool = True, log=print) -> dict:
    profile = profile or load_profile()
    if fetch:
        listings = gather(profile, sources, pages, use_browser, log)
    else:
        listings = dedupe(load_saved_listings() + (load_inbox(log) if "inbox" in sources else []))
    if refresh_rents and fetch and set(sources) - {"inbox"}:
        refresh_rental_comps(listings, profile, use_browser=use_browser, log=log)
    result = rank_listings(listings, profile)
    paths = report.write(result, profile, REPORTS_DIR)
    log(f"Report written: {paths['html']}")
    return {"result": result, "paths": {k: str(v) for k, v in paths.items()}}


def analyse_single(listing: Listing, profile: dict | None = None):
    from .scoring import assess

    profile = profile or load_profile()
    return assess(listing, profile)


def latest_report_json() -> Path | None:
    files = sorted(REPORTS_DIR.glob("shortlist-*.json"))
    return files[-1] if files else None
