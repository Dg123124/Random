"""Financial maths for WA residential investment property.

Everything here is a screening estimate, not credit or tax advice. Rates and
thresholds are kept in module-level tables so they are easy to update when
the State or Federal budgets change them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# --- WA transfer (stamp) duty, general rate. (upper_bound, base, rate_per_dollar_over, lower_bound)
WA_DUTY_BRACKETS = [
    (120_000, 0.0, 0.019, 0),
    (150_000, 2_280.0, 0.0285, 120_000),
    (360_000, 3_135.0, 0.038, 150_000),
    (725_000, 11_115.0, 0.0475, 360_000),
    (float("inf"), 28_453.0, 0.0515, 725_000),
]

# --- WA land tax scale on aggregated unimproved land value (2025-26).
WA_LAND_TAX_BRACKETS = [
    (300_000, 0.0, 0.0, 0),
    (420_000, 300.0, 0.0, 300_000),
    (1_000_000, 300.0, 0.0025, 420_000),
    (1_800_000, 1_750.0, 0.009, 1_000_000),
    (5_000_000, 8_950.0, 0.018, 1_800_000),
    (11_000_000, 66_550.0, 0.020, 5_000_000),
    (float("inf"), 186_550.0, 0.0267, 11_000_000),
]
MRIT_RATE = 0.0014  # Metropolitan Region Improvement Tax on value above the threshold
MRIT_THRESHOLD = 300_000

# --- Australian resident individual income tax, 2026-27.
INCOME_TAX_BRACKETS = [
    (18_200, 0.0, 0.0, 0),
    (45_000, 0.0, 0.15, 18_200),
    (135_000, 4_020.0, 0.30, 45_000),
    (190_000, 31_020.0, 0.37, 135_000),
    (float("inf"), 51_370.0, 0.45, 190_000),
]
MEDICARE_LEVY = 0.02
MEDICARE_LOW_THRESHOLD = 27_222

# --- Rough lenders mortgage insurance, as a share of the loan, by LVR band.
LMI_TABLE = [(0.80, 0.0), (0.85, 0.010), (0.90, 0.020), (0.95, 0.038), (1.00, 0.050)]

CREDIT_CARD_ASSESSMENT_RATE = 0.038  # monthly commitment per dollar of limit


def _scale(amount: float, brackets) -> float:
    for upper, base, rate, lower in brackets:
        if amount <= upper:
            return base + max(0.0, amount - lower) * rate
    raise ValueError("bracket table must end with infinity")


def wa_transfer_duty(price: float) -> float:
    """General-rate WA transfer duty on a residential purchase."""
    return round(_scale(max(0.0, price), WA_DUTY_BRACKETS), 2)


def wa_land_tax(unimproved_value: float, metro: bool = True) -> float:
    tax = _scale(max(0.0, unimproved_value), WA_LAND_TAX_BRACKETS)
    if metro and unimproved_value > MRIT_THRESHOLD:
        tax += (unimproved_value - MRIT_THRESHOLD) * MRIT_RATE
    return round(tax, 2)


def low_income_tax_offset(taxable: float) -> float:
    if taxable <= 37_500:
        return 700.0
    if taxable <= 45_000:
        return 700.0 - (taxable - 37_500) * 0.05
    if taxable <= 66_667:
        return max(0.0, 325.0 - (taxable - 45_000) * 0.015)
    return 0.0


def income_tax(taxable: float) -> float:
    """Income tax plus Medicare levy for an Australian resident."""
    taxable = max(0.0, taxable)
    tax = max(0.0, _scale(taxable, INCOME_TAX_BRACKETS) - low_income_tax_offset(taxable))
    if taxable > MEDICARE_LOW_THRESHOLD:
        tax += taxable * MEDICARE_LEVY
    return round(tax, 2)


def marginal_rate(taxable: float) -> float:
    for upper, _base, rate, _lower in INCOME_TAX_BRACKETS:
        if taxable <= upper:
            return rate + (MEDICARE_LEVY if taxable > MEDICARE_LOW_THRESHOLD else 0.0)
    return 0.47


def monthly_repayment(principal: float, annual_rate_pct: float, years: float) -> float:
    """Principal and interest repayment per month."""
    if principal <= 0:
        return 0.0
    n = max(1, round(years * 12))
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def interest_only_repayment(principal: float, annual_rate_pct: float) -> float:
    return max(0.0, principal) * annual_rate_pct / 100 / 12


def lmi_estimate(loan: float, price: float) -> float:
    if price <= 0 or loan <= 0:
        return 0.0
    lvr = loan / price
    for ceiling, pct in LMI_TABLE:
        if lvr <= ceiling + 1e-9:
            return round(loan * pct, 2)
    return round(loan * LMI_TABLE[-1][1], 2)


@dataclass
class Purchase:
    price: float
    duty: float
    other_costs: float
    cash_used: float
    base_loan: float
    lmi: float
    loan: float
    lvr: float
    within_preapproval: bool
    shortfall: float  # how much more loan or cash you would need (0 if affordable)

    def to_dict(self) -> dict:
        return asdict(self)


def structure_purchase(price: float, profile: dict) -> Purchase:
    """Work out how a purchase would be funded from cash + pre-approved loan."""
    pre = profile["preapproval"]
    assumptions = profile["assumptions"]
    duty = wa_transfer_duty(price)
    other = float(assumptions["other_purchase_costs"])
    cash_usable = max(0.0, float(pre["cash_available"]) - float(pre.get("cash_buffer", 0)))
    total_needed = price + duty + other
    base_loan = max(0.0, total_needed - cash_usable)
    # Costs must be paid in cash; the loan can only fund the price itself.
    base_loan = min(base_loan, price)
    cash_used = total_needed - base_loan
    lmi = lmi_estimate(base_loan, price)
    loan = base_loan + lmi
    loan_limit = float(pre["loan_amount"])
    shortfall = max(0.0, loan - loan_limit) + max(0.0, cash_used - cash_usable)
    return Purchase(
        price=price,
        duty=duty,
        other_costs=other,
        cash_used=round(cash_used, 2),
        base_loan=round(base_loan, 2),
        lmi=lmi,
        loan=round(loan, 2),
        lvr=round(base_loan / price, 4) if price else 0.0,
        within_preapproval=shortfall <= 0.5,
        shortfall=round(shortfall, 2),
    )


def max_purchase_price(profile: dict) -> float:
    """Highest price that the pre-approval plus usable cash can fund (binary search)."""
    lo, hi = 0.0, float(profile["preapproval"]["loan_amount"]) + float(
        profile["preapproval"]["cash_available"]
    ) + 1
    for _ in range(60):
        mid = (lo + hi) / 2
        if structure_purchase(mid, profile).within_preapproval:
            lo = mid
        else:
            hi = mid
    return round(lo, -3) if lo >= 1000 else round(lo, 2)


def _applicant_incomes(profile: dict) -> list[float]:
    inc = profile["income"]
    salaries = [float(inc.get("applicant1_gross_salary", 0)), float(inc.get("applicant2_gross_salary", 0))]
    applicants = [s for s in salaries if s > 0] or [0.0]
    other = float(inc.get("other_taxable_income", 0))
    applicants[0] += other
    return applicants


def _split_tax_change(applicants: list[float], extra_income: float) -> float:
    """Change in household tax when ``extra_income`` (may be negative) is split evenly."""
    share = extra_income / len(applicants)
    return sum(income_tax(a + share) - income_tax(a) for a in applicants)


def household_net_monthly(profile: dict, extra_taxable: float = 0.0) -> float:
    applicants = _applicant_incomes(profile)
    gross = sum(applicants) + extra_taxable
    tax = sum(income_tax(a) for a in applicants) + _split_tax_change(applicants, extra_taxable)
    return (gross - tax) / 12


@dataclass
class CashFlow:
    weekly_rent: float
    annual_rent_collected: float
    management: float
    letting: float
    maintenance: float
    insurance: float
    council_water: float
    strata: float
    land_tax: float
    interest: float
    principal: float
    depreciation: float
    operating_costs: float
    pre_tax_annual: float
    tax_effect_annual: float  # positive = tax refund (negative gearing), negative = extra tax
    after_tax_annual: float
    gross_yield_pct: float
    net_yield_pct: float
    repayment_monthly: float
    breakdown: dict = field(default_factory=dict)

    @property
    def pre_tax_weekly(self) -> float:
        return self.pre_tax_annual / 52

    @property
    def after_tax_weekly(self) -> float:
        return self.after_tax_annual / 52

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pre_tax_weekly"] = round(self.pre_tax_weekly, 2)
        d["after_tax_weekly"] = round(self.after_tax_weekly, 2)
        return d


def is_unit_like(property_type: str) -> bool:
    return (property_type or "").lower() in {"unit", "apartment", "flat", "studio"}


def property_cash_flow(
    price: float,
    weekly_rent: float,
    loan: float,
    profile: dict,
    property_type: str = "house",
    strata_annual: float | None = None,
    council_annual: float | None = None,
) -> CashFlow:
    pre = profile["preapproval"]
    a = profile["assumptions"]
    unit = is_unit_like(property_type)
    rate = float(pre["interest_rate"])

    weeks_let = max(0.0, 52 - float(a["vacancy_weeks_per_year"]))
    rent_collected = weekly_rent * weeks_let
    management = rent_collected * float(a["property_management_pct"]) / 100
    letting = weekly_rent * float(a["letting_fee_weeks"]) * 1.1
    maintenance = rent_collected * float(a["maintenance_pct_of_rent"]) / 100
    insurance = float(a["insurance_annual_unit"] if unit else a["insurance_annual_house"])
    council = (
        float(council_annual)
        if council_annual
        else float(a["council_water_annual_unit"] if unit else a["council_water_annual_house"])
    )
    if strata_annual is None:
        strata = float(a["strata_annual_default"]) if unit or property_type in {"townhouse", "villa"} else 0.0
    else:
        strata = float(strata_annual)
    land_share = float(a["land_value_share_unit"] if unit else a["land_value_share_house"])
    land_tax = wa_land_tax(price * land_share, metro=True)
    operating = management + letting + maintenance + insurance + council + strata + land_tax

    io_years = float(pre.get("interest_only_years", 0)) if pre.get("repayment_type") == "IO" else 0.0
    if io_years > 0:
        repayment = interest_only_repayment(loan, rate)
        interest = loan * rate / 100
        principal = 0.0
    else:
        repayment = monthly_repayment(loan, rate, float(pre["loan_term_years"]))
        interest, principal = _first_year_split(loan, rate, repayment)

    depreciation = float(a.get("depreciation_annual", 0))
    pre_tax = rent_collected - operating - repayment * 12
    taxable_result = rent_collected - operating - interest - depreciation
    tax_change = _split_tax_change(_applicant_incomes(profile), taxable_result)
    after_tax = pre_tax - tax_change

    return CashFlow(
        weekly_rent=round(weekly_rent, 2),
        annual_rent_collected=round(rent_collected, 2),
        management=round(management, 2),
        letting=round(letting, 2),
        maintenance=round(maintenance, 2),
        insurance=round(insurance, 2),
        council_water=round(council, 2),
        strata=round(strata, 2),
        land_tax=round(land_tax, 2),
        interest=round(interest, 2),
        principal=round(principal, 2),
        depreciation=round(depreciation, 2),
        operating_costs=round(operating, 2),
        pre_tax_annual=round(pre_tax, 2),
        tax_effect_annual=round(-tax_change, 2),
        after_tax_annual=round(after_tax, 2),
        gross_yield_pct=round(weekly_rent * 52 / price * 100, 2) if price else 0.0,
        net_yield_pct=round((rent_collected - operating) / price * 100, 2) if price else 0.0,
        repayment_monthly=round(repayment, 2),
    )


def _first_year_split(loan: float, rate_pct: float, repayment: float) -> tuple[float, float]:
    balance, interest_total, r = loan, 0.0, rate_pct / 100 / 12
    for _ in range(12):
        interest = balance * r
        interest_total += interest
        balance -= repayment - interest
    return interest_total, loan - balance


@dataclass
class Serviceability:
    assessment_rate: float
    net_income_monthly: float
    living_expenses_monthly: float
    new_loan_commitment: float
    existing_mortgage_commitment: float
    other_commitments: float
    surplus_monthly: float
    dti: float
    passes: bool

    def to_dict(self) -> dict:
        return asdict(self)


def serviceability(profile: dict, new_loan: float, new_weekly_rent: float) -> Serviceability:
    """Approximate a bank serviceability test (APRA buffer, shaded rent, HEM floor)."""
    pre, inc, exp, cur, a = (
        profile["preapproval"],
        profile["income"],
        profile["expenses"],
        profile["current_mortgage"],
        profile["assumptions"],
    )
    buffer = float(a["serviceability_buffer_pct"])
    assess_rate = float(pre["interest_rate"]) + buffer
    shading = float(a["rental_income_shading_pct"]) / 100
    rent_annual = (float(inc.get("existing_rental_income_weekly", 0)) + new_weekly_rent) * 52 * shading
    net_monthly = household_net_monthly(profile, rent_annual)

    couple = float(inc.get("applicant2_gross_salary", 0)) > 0
    hem = float(a["hem_monthly_couple"] if couple else a["hem_monthly_single"]) + float(
        a["hem_per_dependant"]
    ) * float(exp.get("dependants", 0))
    living = max(float(exp["monthly_living"]), hem)

    new_commit = monthly_repayment(new_loan, assess_rate, float(pre["loan_term_years"]))
    existing = 0.0
    existing_debt = 0.0
    if cur.get("has_mortgage"):
        existing_debt = float(cur["balance"])
        existing = max(
            float(cur.get("monthly_repayment", 0)),
            monthly_repayment(existing_debt, float(cur["interest_rate"]) + buffer, 25),
        )
    other = float(exp.get("monthly_other_debt_repayments", 0)) + float(
        exp.get("credit_card_limits", 0)
    ) * CREDIT_CARD_ASSESSMENT_RATE

    surplus = net_monthly - living - new_commit - existing - other
    gross_income = sum(_applicant_incomes(profile)) + float(inc.get("existing_rental_income_weekly", 0)) * 52 + new_weekly_rent * 52
    total_debt = new_loan + existing_debt + float(exp.get("credit_card_limits", 0))
    dti = total_debt / gross_income if gross_income else float("inf")
    return Serviceability(
        assessment_rate=round(assess_rate, 2),
        net_income_monthly=round(net_monthly, 2),
        living_expenses_monthly=round(living, 2),
        new_loan_commitment=round(new_commit, 2),
        existing_mortgage_commitment=round(existing, 2),
        other_commitments=round(other, 2),
        surplus_monthly=round(surplus, 2),
        dti=round(dti, 2),
        passes=surplus >= 0 and dti < 6.0,
    )


def household_position(profile: dict, cash_flow: CashFlow) -> dict:
    """Real-world monthly household budget after buying (actual rates, not buffered)."""
    exp, cur = profile["expenses"], profile["current_mortgage"]
    net = household_net_monthly(profile, float(profile["income"].get("existing_rental_income_weekly", 0)) * 52)
    existing_mortgage = float(cur.get("monthly_repayment", 0)) if cur.get("has_mortgage") else 0.0
    before = net - float(exp["monthly_living"]) - existing_mortgage - float(exp.get("monthly_other_debt_repayments", 0))
    after = before + cash_flow.after_tax_annual / 12
    return {
        "monthly_surplus_before": round(before, 2),
        "monthly_surplus_after": round(after, 2),
        "property_after_tax_monthly": round(cash_flow.after_tax_annual / 12, 2),
    }


def forecast(
    price: float,
    weekly_rent: float,
    loan: float,
    cash_invested: float,
    profile: dict,
    property_type: str = "house",
    strata_annual: float | None = None,
) -> list[dict]:
    """Year-by-year projection of rent, value, loan balance, cash flow and equity."""
    a, pre = profile["assumptions"], profile["preapproval"]
    years = int(a["forecast_years"])
    rent_g = float(a["rental_growth_pct"]) / 100
    cap_g = float(a["capital_growth_pct"]) / 100
    rate = float(pre["interest_rate"])
    io_years = int(pre.get("interest_only_years", 0)) if pre.get("repayment_type") == "IO" else 0
    term = float(pre["loan_term_years"])

    balance = loan
    value = price
    rent = weekly_rent
    cumulative = 0.0
    rows = []
    for year in range(1, years + 1):
        cf = property_cash_flow(value, rent, balance, profile, property_type, strata_annual)
        if year <= io_years:
            pay = interest_only_repayment(balance, rate)
            year_interest = balance * rate / 100
        else:
            remaining = max(1.0, term - (year - 1))
            pay = monthly_repayment(balance, rate, remaining)
            year_interest, principal = _first_year_split(balance, rate, pay)
            balance = max(0.0, balance - principal)
        pre_tax = cf.annual_rent_collected - cf.operating_costs - pay * 12
        taxable = cf.annual_rent_collected - cf.operating_costs - year_interest - cf.depreciation
        after_tax = pre_tax - _split_tax_change(_applicant_incomes(profile), taxable)
        cumulative += after_tax
        value *= 1 + cap_g
        rows.append(
            {
                "year": year,
                "weekly_rent": round(rent, 0),
                "property_value": round(value, 0),
                "loan_balance": round(balance, 0),
                "equity": round(value - balance, 0),
                "after_tax_cash_flow": round(after_tax, 0),
                "cumulative_cash_flow": round(cumulative, 0),
                "total_return": round(value - balance - cash_invested + cumulative, 0),
            }
        )
        rent *= 1 + rent_g
    return rows
