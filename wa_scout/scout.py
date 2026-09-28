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
from .sources import domain_api, manual, realestate, reiwa
from .sources.http import FetchError

INBOX_DIR = DATA_DIR / "inbox"
LISTINGS_PATH = DATA_DIR / "listings.json"
COMPS_PATH = DATA_DIR / "rental_comps.json"
ALL_SOURCES = ("inbox", "reiwa", "domain", "realestate")
SUBURB_STATS_PATH = DATA_DIR / "suburb_stats.csv"
WORKERS = 4  # concurrent requests; http.fetch still spaces request starts apart

# Default REIWA scan when no suburbs are chosen: established Perth metro suburbs
# where typical house prices sit roughly between $600k and $1.2M. The distance
# filter (criteria.max_km_to_cbd) trims these further.
DEFAULT_REIWA_SUBURBS = [
    # North
    "Balga", "Girrawheen", "Koondoola", "Marangaroo", "Alexander Heights", "Mirrabooka", "Nollamara",
    "Westminster", "Balcatta", "Stirling", "Hamersley", "Warwick", "Greenwood", "Kingsley", "Landsdale",
    "Madeley", "Wanneroo", "Dianella",
    # North east and hills
    "Morley", "Noranda", "Beechboro", "Embleton", "Bayswater", "Bassendean", "Eden Hill", "Lockridge",
    "Kiara", "Ashfield", "Caversham", "Guildford", "Midland", "Midvale", "Swan View", "Woodbridge",
    "Bellevue", "Stratton", "Ellenbrook",
    # East
    "Forrestfield", "High Wycombe", "Maida Vale", "Kewdale", "Cloverdale", "Belmont", "Redcliffe", "Rivervale",
    # South east
    "Cannington", "Queens Park", "East Cannington", "Beckenham", "Kenwick", "Wilson", "Maddington",
    "Gosnells", "Thornlie", "Huntingdale", "Langford", "Lynwood", "Ferndale", "Parkwood", "Bentley",
    "St James", "Canning Vale",
    # South
    "Hamilton Hill", "Spearwood", "Coolbellup", "Kardinya", "Bibra Lake", "South Lake", "Yangebup",
    "Beeliar", "Success", "Hammond Park", "Samson", "O'Connor", "Willagee", "Beaconsfield",
]


def _card_prefilter(listing: Listing, crit: dict, price_cap: float) -> bool:
    """Cheap filter on search-card fields before fetching each detail page."""
    types = [t.lower() for t in crit.get("property_types") or []]
    if types and listing.property_type not in types:
        return False
    if listing.price is None or listing.price > price_cap:
        return False
    for attr, key in (("bedrooms", "bedrooms_min"), ("bathrooms", "bathrooms_min"), ("car_spaces", "car_spaces_min")):
        value = getattr(listing, attr)
        if crit.get(key) and value is not None and value < crit[key]:
            return False
    if crit.get("bedrooms_max") and listing.bedrooms and listing.bedrooms > crit["bedrooms_max"]:
        return False
    return listing.extra.get("status") != "under offer"


def gather_reiwa(crit: dict, price_cap: float, pages: int, log=print) -> list[Listing]:
    suburbs = [s for s in crit.get("suburbs_include") or [] if s.strip()] or DEFAULT_REIWA_SUBURBS
    exclude = {s.strip().lower() for s in crit.get("suburbs_exclude") or []}
    from concurrent.futures import ThreadPoolExecutor

    found: dict[str, Listing] = {}
    todo = [s for s in suburbs if s.lower() not in exclude]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for batch in pool.map(lambda sub: reiwa.search_suburb(sub, max_pages=pages, log=log), todo):
            for listing in batch:
                found.setdefault(listing.id, listing)
    candidates = [l for l in found.values() if _card_prefilter(l, crit, price_cap)]
    log(f"[reiwa] {len(found)} listings seen, {len(candidates)} pass the quick filter; fetching details")
    def detail(listing: Listing) -> Listing | None:
        try:
            return reiwa.enrich(listing)
        except FetchError as exc:
            log(f"[reiwa] detail failed for {listing.url}: {exc}")
            return None

    enriched: list[Listing] = []
    stats: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, listing in enumerate(pool.map(detail, candidates), 1):
            if listing is None:
                continue
            if listing.extra.get("suburb_stats"):
                stats[listing.suburb] = {"postcode": listing.postcode, **listing.extra["suburb_stats"]}
            enriched.append(listing)
            if i % 25 == 0:
                log(f"[reiwa] details {i}/{len(candidates)}")
    update_suburb_stats(stats, source="REIWA suburb stats (listing page)")
    return enriched


def update_suburb_stats(stats: dict[str, dict], source: str) -> None:
    """Upsert house median rent/price rows into data/suburb_stats.csv."""
    import csv

    if not stats:
        return
    header_lines, rows = [], {}
    if SUBURB_STATS_PATH.exists():
        lines = SUBURB_STATS_PATH.read_text(encoding="utf-8").splitlines()
        header_lines = [l for l in lines if l.startswith("#")]
        for row in csv.DictReader(l for l in lines if not l.startswith("#")):
            rows[(row["suburb"].lower(), row["property_type"])] = row
    month = dt.date.today().strftime("%Y-%m")
    for suburb, st in stats.items():
        rows[(suburb.lower(), "house")] = {
            "suburb": suburb, "postcode": st.get("postcode") or "", "property_type": "house",
            "median_weekly_rent": st.get("median_rent") or "", "median_price": st.get("median_price") or "",
            "source": source, "as_of": month,
        }
    fields = ["suburb", "postcode", "property_type", "median_weekly_rent", "median_price", "source", "as_of"]
    with open(SUBURB_STATS_PATH, "w", encoding="utf-8", newline="") as fh:
        for line in header_lines:
            fh.write(line + "\n")
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows.values(), key=lambda r: (r["suburb"], r["property_type"])):
            writer.writerow({k: row.get(k, "") for k in fields})


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
    if "reiwa" in sources:
        found += gather_reiwa(crit, price_max, min(pages, 3), log)
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


def refresh_rental_comps(listings: list[Listing], profile: dict, max_suburbs: int = 40,
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
        batch = reiwa.rental_comps(suburb, log=log)
        if not batch:
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
