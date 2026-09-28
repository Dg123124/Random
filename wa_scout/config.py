"""User profile: finances, search criteria and modelling assumptions.

The profile is a plain JSON file (``profile.json`` by default) so it can be edited
by hand, by the web UI, or by the Claude Code agent. Anything missing from the
file falls back to ``DEFAULT_PROFILE``.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
PROFILE_PATH = Path(os.environ.get("WA_SCOUT_PROFILE", ROOT / "profile.json"))

PROPERTY_TYPES = ["house", "townhouse", "villa", "unit", "apartment", "duplex", "land"]

DEFAULT_PROFILE: dict = {
    "preapproval": {
        # Maximum loan amount on your pre-approval letter.
        "loan_amount": 600000,
        # Cash you can put toward deposit, duty and purchase costs.
        "cash_available": 120000,
        # Keep this much cash aside as a buffer (not spent on the purchase).
        "cash_buffer": 15000,
        "interest_rate": 6.09,
        "loan_term_years": 30,
        # "PI" (principal and interest) or "IO" (interest only).
        "repayment_type": "PI",
        "interest_only_years": 0,
        "first_home_buyer": False,
    },
    "income": {
        # Annual gross (before tax) salaries. Use 0 for a single applicant.
        "applicant1_gross_salary": 145000,
        "applicant2_gross_salary": 85000,
        # Other taxable annual income (bonuses, side business, dividends).
        "other_taxable_income": 0,
        # Gross weekly rent you already receive from other investment properties.
        "existing_rental_income_weekly": 0,
    },
    "expenses": {
        # Household living costs per month (food, bills, transport, kids, etc.).
        "monthly_living": 4800,
        # Car loans, personal loans, BNPL, HECS/HELP repayments per month.
        "monthly_other_debt_repayments": 0,
        # Total credit card limits (banks assess ~3.8% of the limit per month).
        "credit_card_limits": 10000,
        "dependants": 0,
    },
    "current_mortgage": {
        "has_mortgage": True,
        "balance": 350000,
        "interest_rate": 6.19,
        "monthly_repayment": 2600,
        "property_value": 750000,
        # True if this is your home (repayments not tax deductible).
        "owner_occupied": True,
    },
    "criteria": {
        "property_types": ["house", "townhouse", "villa"],
        "price_min": 0,
        "price_max": 0,  # 0 = derive from pre-approval
        "bedrooms_min": 3,
        "bedrooms_max": 0,  # 0 = no max
        "bathrooms_min": 1,
        "car_spaces_min": 1,
        "land_size_min_sqm": 0,
        "land_size_max_sqm": 0,
        "building_size_min_sqm": 0,
        # Leave empty to search the whole Perth metro area.
        "suburbs_include": [],
        "suburbs_exclude": [],
        # Straight-line km from the Perth CBD (0 = no limit). ~25 km is roughly a
        # 35 minute drive outside peak hour.
        "max_km_to_cbd": 0,
        # Postcode ranges treated as "metropolitan WA" (Perth + Peel).
        "metro_postcodes": [[6000, 6199], [6207, 6214]],
        "max_listings_to_scan": 400,
        "top_n": 20,
    },
    "assumptions": {
        "rental_growth_pct": 4.0,
        "capital_growth_pct": 5.0,
        "forecast_years": 10,
        "vacancy_weeks_per_year": 2,
        "property_management_pct": 8.25,  # incl. GST
        "letting_fee_weeks": 1,
        "maintenance_pct_of_rent": 5.0,
        "insurance_annual_house": 1900,
        "insurance_annual_unit": 700,
        "council_water_annual_house": 2700,
        "council_water_annual_unit": 2100,
        "strata_annual_default": 3600,
        "land_value_share_house": 0.55,
        "land_value_share_unit": 0.20,
        "other_purchase_costs": 3500,  # conveyancing, searches, building & pest
        "depreciation_annual": 0,
        # Banks assess new loans at the product rate plus this buffer (APRA).
        "serviceability_buffer_pct": 3.0,
        # Banks only count this share of rental income when assessing.
        "rental_income_shading_pct": 80,
        "hem_monthly_single": 2400,
        "hem_monthly_couple": 3400,
        "hem_per_dependant": 450,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_profile(path: Path | str | None = None) -> dict:
    path = Path(path) if path else PROFILE_PATH
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return deep_merge(DEFAULT_PROFILE, json.load(fh))
    return copy.deepcopy(DEFAULT_PROFILE)


def save_profile(profile: dict, path: Path | str | None = None) -> Path:
    path = Path(path) if path else PROFILE_PATH
    merged = deep_merge(DEFAULT_PROFILE, profile)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
    return path
