"""Command line entry point: ``python -m wa_scout <command>``."""

from __future__ import annotations

import argparse
import json
import sys

from . import finance, scout
from .config import load_profile
from .listings import Listing


def _print_budget(profile: dict) -> None:
    from .server import budget_summary

    b = budget_summary(profile)
    p, s = b["purchase_at_max"], b["serviceability_no_rent"]
    print(f"Max purchase price:      ${b['max_purchase_price']:,.0f}")
    print(f"  loan at that price:    ${p['loan']:,.0f} (LVR {p['lvr']:.0%}, LMI ${p['lmi']:,.0f})")
    print(f"  cash used:             ${p['cash_used']:,.0f} (duty ${p['duty']:,.0f})")
    print(f"Net household income:    ${b['net_income_monthly']:,.0f}/month")
    print(f"Bank test surplus (no rent counted): ${s['surplus_monthly']:,.0f}/month at {s['assessment_rate']}%  DTI {s['dti']}x")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="wa_scout", description="Rank metropolitan WA listings against your finances.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="start the local web app")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--host", default="127.0.0.1")

    p_scout = sub.add_parser("scout", help="gather listings, refresh rents, rank the top 20")
    p_scout.add_argument("--sources", default=",".join(scout.ALL_SOURCES),
                         help="comma list of: inbox, domain, realestate")
    p_scout.add_argument("--pages", type=int, default=5)
    p_scout.add_argument("--no-browser", action="store_true", help="never launch Playwright")
    p_scout.add_argument("--no-rent-refresh", action="store_true")
    p_scout.add_argument("--offline", action="store_true", help="re-rank data/listings.json without fetching")
    p_scout.add_argument("--json", action="store_true", help="print the shortlist JSON path only")

    sub.add_parser("budget", help="show your maximum purchase price and serviceability")

    p_an = sub.add_parser("analyse", help="assess one property")
    p_an.add_argument("--url", default="")
    p_an.add_argument("--price", default="")
    p_an.add_argument("--suburb", default="")
    p_an.add_argument("--postcode", default="")
    p_an.add_argument("--type", default="house")
    p_an.add_argument("--beds", type=int)
    p_an.add_argument("--baths", type=int)
    p_an.add_argument("--cars", type=int)
    p_an.add_argument("--land", type=float)
    p_an.add_argument("--rent", type=float, help="known weekly rent, if any")
    p_an.add_argument("--strata", type=float, help="annual strata levies")

    args = parser.parse_args(argv)
    profile = load_profile()

    if args.cmd == "serve":
        from .server import serve

        serve(args.port, args.host)
        return 0
    if args.cmd == "budget":
        _print_budget(profile)
        return 0
    if args.cmd == "scout":
        out = scout.run(
            profile,
            sources=tuple(s.strip() for s in args.sources.split(",") if s.strip()),
            pages=args.pages,
            use_browser=not args.no_browser,
            refresh_rents=not args.no_rent_refresh,
            fetch=not args.offline,
            log=(lambda *_: None) if args.json else print,
        )
        if args.json:
            print(out["paths"]["json"])
        else:
            from .report import markdown, payload

            print()
            print(markdown(payload(out["result"], profile)))
        return 0
    if args.cmd == "analyse":
        if args.url and not args.price:
            from .sources import realestate

            listing = realestate.fetch_listing(args.url)
            if listing is None:
                print("Could not read that page; pass --price/--suburb/--beds etc. instead.", file=sys.stderr)
                return 1
        else:
            listing = Listing.from_dict({
                "id": "cli", "url": args.url, "price_text": args.price, "suburb": args.suburb,
                "postcode": args.postcode, "property_type": args.type, "bedrooms": args.beds,
                "bathrooms": args.baths, "car_spaces": args.cars, "land_size_sqm": args.land,
                "strata_annual": args.strata,
                "extra": {"current_weekly_rent": args.rent} if args.rent else {},
            })
        result = scout.analyse_single(listing, profile)
        if result is None:
            print("Need a price to assess.", file=sys.stderr)
            return 1
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
