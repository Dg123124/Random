"""Score each listing against the user's finances and rank the best 20."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import finance
from .listings import Listing, matches_criteria
from .rent import RentEstimate, estimate_rent, load_baseline, load_comps, load_suburb_stats, suburb_median_price

WEIGHTS = {
    "cash_flow": 25,
    "yield": 15,
    "serviceability": 20,
    "budget_fit": 10,
    "value": 10,
    "growth": 10,
    "features": 10,
}


def _lerp(value: float, lo: float, hi: float, points: float) -> float:
    """Map value in [lo, hi] linearly to [0, points], clamped."""
    if hi == lo:
        return points if value >= hi else 0.0
    frac = (value - lo) / (hi - lo)
    return round(max(0.0, min(1.0, frac)) * points, 2)


@dataclass
class Assessment:
    listing: Listing
    rent: RentEstimate
    purchase: finance.Purchase
    cash_flow: finance.CashFlow
    service: finance.Serviceability
    household: dict
    projection: list[dict]
    suburb_median: float | None
    components: dict
    score: float
    verdict: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    rank: int | None = None

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "score": self.score,
            "verdict": self.verdict,
            "listing": self.listing.to_dict(),
            "rent": self.rent.to_dict(),
            "purchase": self.purchase.to_dict(),
            "cash_flow": self.cash_flow.to_dict(),
            "serviceability": self.service.to_dict(),
            "household": self.household,
            "projection": self.projection,
            "suburb_median_price": self.suburb_median,
            "components": self.components,
            "pros": self.pros,
            "cons": self.cons,
        }


def assess(
    listing: Listing,
    profile: dict,
    max_price: float | None = None,
    suburb_stats: dict | None = None,
    comps: list | None = None,
    baseline: dict | None = None,
) -> Assessment | None:
    if not listing.price:
        return None
    max_price = max_price or finance.max_purchase_price(profile)
    rent = estimate_rent(listing, suburb_stats, comps, baseline)
    purchase = finance.structure_purchase(listing.price, profile)
    cf = finance.property_cash_flow(
        listing.price, rent.weekly, purchase.loan, profile, listing.property_type,
        listing.strata_annual, listing.council_annual,
    )
    service = finance.serviceability(profile, purchase.loan, rent.weekly)
    household = finance.household_position(profile, cf)
    projection = finance.forecast(
        listing.price, rent.weekly, purchase.loan, purchase.cash_used, profile,
        listing.property_type, listing.strata_annual,
    )
    median = suburb_median_price(listing, suburb_stats)
    crit = profile["criteria"]
    pros: list[str] = []
    cons: list[str] = []

    comp = {}
    weekly_cf = cf.after_tax_weekly
    comp["cash_flow"] = _lerp(weekly_cf, -300, 100, WEIGHTS["cash_flow"])
    (pros if weekly_cf >= 0 else cons).append(
        f"After-tax cash flow {'+' if weekly_cf >= 0 else '-'}${abs(weekly_cf):,.0f}/week"
    )

    comp["yield"] = _lerp(cf.gross_yield_pct, 3.0, 6.5, WEIGHTS["yield"])
    if cf.gross_yield_pct >= 5.0:
        pros.append(f"Gross yield {cf.gross_yield_pct:.1f}%")
    elif cf.gross_yield_pct < 4.0:
        cons.append(f"Low gross yield {cf.gross_yield_pct:.1f}%")

    comp["serviceability"] = _lerp(service.surplus_monthly, 0, 1500, WEIGHTS["serviceability"])
    if not service.passes:
        cons.append(
            f"Tight on bank servicing (estimated shortfall ${-service.surplus_monthly:,.0f}/mo at "
            f"{service.assessment_rate:.2f}%); confirm with your lender"
        )
    if service.dti >= 6:
        cons.append(f"Debt-to-income {service.dti:.1f}x: many lenders limit lending at 6x or more")
    elif service.surplus_monthly > 1000:
        pros.append(f"Comfortable serviceability headroom (${service.surplus_monthly:,.0f}/mo)")

    usage = listing.price / max_price if max_price else 1.0
    comp["budget_fit"] = _lerp(1.0 - usage, 0.0, 0.15, WEIGHTS["budget_fit"])
    if not purchase.within_preapproval:
        comp["budget_fit"] = 0.0
        cons.append(f"Over budget: short by ${purchase.shortfall:,.0f} (loan or cash)")
    elif usage <= 0.85:
        pros.append(f"Leaves budget room ({usage:.0%} of your max price ${max_price:,.0f})")
    if purchase.lmi > 0:
        cons.append(f"LVR {purchase.lvr:.0%}: estimated LMI ${purchase.lmi:,.0f}")

    if median:
        diff = (listing.price - median) / median
        comp["value"] = _lerp(-diff, -0.15, 0.15, WEIGHTS["value"])
        if diff <= -0.05:
            pros.append(f"{abs(diff):.0%} below {listing.suburb} median (${median:,.0f})")
        elif diff >= 0.10:
            cons.append(f"{diff:.0%} above {listing.suburb} median (${median:,.0f})")
    else:
        comp["value"] = WEIGHTS["value"] / 2

    final = projection[-1] if projection else {"total_return": 0}
    multiple = final["total_return"] / purchase.cash_used if purchase.cash_used else 0.0
    comp["growth"] = _lerp(multiple, 0.0, 3.0, WEIGHTS["growth"])
    years = profile["assumptions"]["forecast_years"]
    positive_year = next((r["year"] for r in projection if r["after_tax_cash_flow"] >= 0), None)
    if positive_year and positive_year > 1:
        pros.append(f"Forecast cash-flow positive (after tax) from year {positive_year}")
    elif positive_year is None:
        cons.append(f"Still cash-flow negative after {years} years on current assumptions")

    feat = 0.0
    if listing.property_type in {"house", "duplex", "villa"} and listing.land_size_sqm:
        feat += _lerp(listing.land_size_sqm, 300, 700, 4)
        if listing.land_size_sqm >= 600:
            pros.append(f"{listing.land_size_sqm:,.0f} m² block (land-heavy, growth/subdivision upside)")
    elif listing.property_type in {"house", "duplex", "villa"}:
        feat += 2
    if listing.bedrooms and crit.get("bedrooms_min"):
        feat += min(2, max(0, listing.bedrooms - crit["bedrooms_min"] + 1))
    if listing.bathrooms and listing.bathrooms >= 2:
        feat += 1.5
    if listing.car_spaces and listing.car_spaces >= 2:
        feat += 1.0
    if listing.days_on_market is not None and listing.days_on_market >= 45:
        feat += 1.5
        pros.append(f"{listing.days_on_market} days on market: room to negotiate")
    comp["features"] = round(min(WEIGHTS["features"], feat), 2)

    raw = sum(comp.values())
    score = raw * (0.85 + 0.15 * rent.confidence)
    if rent.confidence < 0.4:
        cons.append("Rent is a metro-level estimate; check local rentals before relying on it")
    if not service.passes:
        score = min(score, 50.0)
    if not purchase.within_preapproval:
        score = min(score, 20.0)
    score = round(score, 1)

    if not purchase.within_preapproval:
        verdict = "Over budget"
    elif not service.passes:
        verdict = "Tight on servicing"
    elif score >= 70:
        verdict = "Strong candidate"
    elif score >= 55:
        verdict = "Worth a look"
    elif score >= 40:
        verdict = "Marginal"
    else:
        verdict = "Pass"

    return Assessment(listing, rent, purchase, cf, service, household, projection, median, comp, score, verdict, pros, cons)


def rank_listings(listings: list[Listing], profile: dict) -> dict:
    """Filter, assess and rank. Returns the top N plus a summary of what was dropped."""
    crit = profile["criteria"]
    max_price = finance.max_purchase_price(profile)
    stats, comps, baseline = load_suburb_stats(), load_comps(), load_baseline()
    assessed: list[Assessment] = []
    rejected: dict[str, int] = {}
    no_price = 0
    for listing in listings[: int(crit.get("max_listings_to_scan") or 10_000)]:
        ok, reasons = matches_criteria(listing, crit, price_cap=max_price)
        if not ok:
            key = reasons[0].split(" ")[0] if reasons else "other"
            rejected[key] = rejected.get(key, 0) + 1
            continue
        result = assess(listing, profile, max_price, stats, comps, baseline)
        if result is None:
            no_price += 1
            continue
        assessed.append(result)

    assessed.sort(key=lambda a: a.score, reverse=True)
    top_n = int(crit.get("top_n") or 20)
    top = assessed[:top_n]
    for i, item in enumerate(top, 1):
        item.rank = i
    return {
        "max_purchase_price": max_price,
        "scanned": len(listings),
        "matched": len(assessed),
        "rejected_by": rejected,
        "no_price": no_price,
        "top": top,
    }
