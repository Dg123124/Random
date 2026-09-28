# WA Property Scout

Find investment properties in metropolitan Western Australia (Perth and Peel) that
actually work for **your** finances. It reads listings, forecasts rent from free
public data, tests every property against your pre-approval, income, expenses and
current mortgage, and ranks a **top 20** for you to look at.

It has three parts:

| Part | What it does |
|---|---|
| `wa_scout/` Python engine | WA transfer duty, LMI, land tax, income tax and negative gearing, bank-style serviceability test, cash flow, 10-year forecast and a 0-100 score. Standard library only. |
| Local web app | Enter your pre-approval, income, expenses, mortgage and what you want (type, price, beds, baths, car spaces, land and floor size, suburbs). Run the scout and browse the ranked list. |
| Claude Code agent skills | `/wa-scout` autonomously searches listings (including realestate.com.au via web search), researches suburb rents, and runs the ranking. Modelled on the Lotlytics plugin layout. |

## Quick start

```bash
git clone <this repo> && cd <repo>
python3 -m wa_scout serve          # open http://localhost:8765
```

1. Fill in each tab on the left (Pre-approval, Income, Expenses, Mortgage, Property,
   Assumptions) and press **Save profile**. The top strip shows your maximum
   purchase price, the cash it needs, and whether you pass a bank-style test.
2. Press **Scout listings now**. The ranked top 20 appears with a score, verdict,
   rent estimate, yield and weekly after-tax cash flow. Click any row for the
   funding breakdown, year-1 cash flow, score parts and the 10-year forecast.
3. Use **Check one property** to assess a single ad you found yourself.

To try it without live data, copy the fictional sample listings into the inbox:

```bash
mkdir -p data/inbox && cp data/sample/sample_listings.json data/inbox/
python3 -m wa_scout scout --sources inbox
```

### Command line

```bash
python3 -m wa_scout budget                 # max price, cash needed, serviceability
python3 -m wa_scout scout                  # gather + refresh rents + rank, writes reports/
python3 -m wa_scout scout --offline        # re-rank saved listings + data/inbox without fetching
python3 -m wa_scout analyse --price "Offers over $549,000" --suburb Midland --postcode 6056 \
    --type house --beds 4 --baths 2 --cars 2 --land 620
```

Each run writes `reports/shortlist-<time>.html|json|csv|md`.

### The autonomous agent (Claude Code)

Open this folder in Claude Code. The skills in `skills/` load automatically
(`.claude/skills` links to them), or install it as a plugin:

```
/plugin marketplace add <your-github-user>/<this-repo>
/plugin install wa-property-scout
```

| Skill | Use it to |
|---|---|
| `/setup-profile` | Be interviewed about your finances and target property; writes `profile.json`. |
| `/wa-scout` | Scour listings suburb by suburb, refresh rents, and report the ranked top 20. |
| `/analyse-listing` | Assess one realestate.com.au / Domain link or typed details. |
| `/refresh-rents` | Look up suburb median rents and prices and store them in `data/suburb_stats.csv`. |

To have it scout every day, run `/loop 24h /wa-scout` or create a scheduled routine
that runs `/wa-scout` each morning.

## Where the listings come from

realestate.com.au has no public API and blocks most automated requests, so the
tool uses several routes and merges the results (duplicates are combined by address):

1. **Inbox** (`data/inbox/*.json|csv`): listings the agent found through web
   search, listings you add in the web app, or a CSV you export yourself. Columns:
   `address, suburb, postcode, property_type, price_text, bedrooms, bathrooms,
   car_spaces, land_size_sqm, building_size_sqm, strata_annual, url, description`.
2. **Domain API** (recommended, official and free tier): register at
   <https://developer.domain.com.au>, then `export DOMAIN_API_KEY=...`.
3. **realestate.com.au** direct: tries a normal request, then a real browser if
   Playwright is installed (`pip install playwright && playwright install chromium`).
   It reads a few pages, waits between requests and caches for 12 hours. Please
   keep it to personal research and respect the site's terms of use.

## How rent is forecast

Best source wins, and each estimate shows its method and a confidence level:

1. The ad says it is leased ("currently leased at $620 pw").
2. Three or more comparable rentals in the same suburb (`data/rental_comps.json`,
   filled by the scout from Domain / realestate.com.au rental listings).
3. The suburb's median rent (`data/suburb_stats.csv`, filled by `/refresh-rents`
   from REIWA, SQM Research and portal suburb profiles), adjusted for bedrooms,
   bathrooms and parking.
4. Perth metro medians (REIWA, August 2026: houses $750/wk at a $960k median, units
   $700/wk at $690k), scaled by bedrooms and price. Low confidence and flagged.

Rent then grows at your assumed rate (default 4% a year) in the forecast.

## How each property is scored (0-100)

| Part | Points | What earns them |
|---|---|---|
| After-tax cash flow | 25 | -$300/wk scores 0, +$100/wk scores full marks |
| Gross yield | 15 | 3% scores 0, 6.5% scores full marks |
| Serviceability | 20 | Monthly surplus in a bank-style test (rate + 3% buffer, 80% of rent, HEM floor, 3.8% of card limits) |
| Budget fit | 10 | Room left under your maximum purchase price |
| Value | 10 | Price against the suburb median, when known |
| Growth | 10 | 10-year total return as a multiple of the cash you put in |
| Features | 10 | Land size, extra bedrooms/bathrooms, parking, days on market |

The total is scaled by rent confidence. A property that fails the bank test is
capped at 50 ("Tight on servicing"), since your lender has the final say; one you can't fund is capped at 20 ("Over
budget"). Verdicts: 70+ Strong candidate, 55+ Worth a look, 40+ Marginal, below
40 Pass. Weights are in `wa_scout/scoring.py`.

## What the finance model includes

- WA transfer duty (general rates), conveyancing and inspection costs, LMI estimate
  above 80% LVR (capitalised into the loan), cash buffer you want to keep.
- Maximum purchase price from pre-approved loan plus usable cash.
- Operating costs: vacancy, management and letting fees, maintenance, insurance,
  council and water, strata, WA land tax plus MRIT on an estimated land value.
- 2026-27 resident tax rates, Medicare levy and LITO, split between applicants, to
  work out the negative-gearing refund or extra tax.
- Your existing mortgage, other debts and card limits in the serviceability test,
  and your real household surplus after buying.

All rates and thresholds sit in tables at the top of `wa_scout/finance.py` so
they are easy to update after a State or Federal budget.

## Your data stays local

`profile.json`, scraped listings, the cache and reports are in `.gitignore`.
`profile.example.json` shows the full profile format.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## Disclaimer

This is a screening tool. Its numbers are estimates and are not financial, tax or
credit advice. Confirm rent with a local property manager, get building, pest and
strata reports, and check your borrowing with your broker before making an offer.
