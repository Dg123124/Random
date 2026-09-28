---
name: wa-scout
description: Autonomously scour metropolitan WA (Perth + Peel) property listings on realestate.com.au and other free sources, forecast rent, test each one against the user's pre-approval and cash flow, and produce a ranked top 20 shortlist. Use when the user asks to find, scout, rank or shortlist WA investment properties.
---

# WA Scout: find and rank the top 20 investment properties

You are the autonomous scouting agent for WA Property Scout. Your job is to gather
as many real, currently-for-sale listings in metropolitan WA as you reasonably can,
feed them to the scoring engine, and report the ranked top 20.

All commands run from the repository root. The engine is stdlib-only Python 3.10+.

## 1. Load the user's position

1. If `profile.json` does not exist, run the `setup-profile` skill first.
2. Run `python -m wa_scout budget` and note the **max purchase price** and whether
   the bank test passes. Read `profile.json` for the criteria (types, beds, baths,
   cars, land size, suburbs). The search price ceiling is `criteria.price_max`, or
   the max purchase price when that is 0.

## 2. Automated sources first

Run:

```
python -m wa_scout scout --pages 5
```

This pulls from `data/inbox/`, REIWA (suburb by suburb, with detail pages for
land size, status and location), the Domain API (if `DOMAIN_API_KEY` is set) and
realestate.com.au (plain HTTP, then Playwright if installed). REIWA normally
provides plenty; realestate.com.au often blocks automated requests. If the log
shows REIWA was blocked or fewer than ~40 listings matched, continue with step 3.

## 3. Agent search (web search + fetch)

Work suburb by suburb. If `criteria.suburbs_include` is empty, pick 15-25 suburbs
across the Perth metro and Peel regions where typical prices sit at or below the
price ceiling (use recent REIWA/Domain/realestate.com.au suburb medians you find
by searching). Cover north, south, east and hills corridors, and include Mandurah
and Rockingham/Kwinana if in budget.

For each suburb:

1. WebSearch queries such as:
   - `site:realestate.com.au property-house-wa-<suburb-slug> for sale`
   - `<Suburb> WA 6xxx house for sale <beds> bedroom realestate.com.au`
   - `<Suburb> WA house for sale domain.com.au` (Domain and agency sites
     syndicate the same listings and are often fetchable when realestate.com.au is not)
2. For each promising result, try WebFetch on the listing page and extract: address,
   suburb, postcode, property type, price text, beds, baths, car spaces, land size,
   floor area, strata levies, council rates, days on market / listed date, and any
   statement of current or appraised rent. If the fetch is blocked, use only the
   details visible in the search result title/snippet.
3. Only keep listings that are for sale now, in WA postcodes 6000-6199 or 6207-6214,
   and plausibly within the price ceiling. Skip "under offer" and "sold".

**Never invent data.** Leave unknown fields as `null`. A listing with no usable
price (e.g. "Contact agent") can be kept only if a price guide appears somewhere
public; put the source in `headline`.

Write what you found to `data/inbox/agent-YYYYMMDD.json` (one file per run,
overwrite if re-run the same day):

```json
{"listings": [
  {"url": "https://www.realestate.com.au/property-house-wa-midland-...",
   "address": "12 Example Street", "suburb": "Midland", "postcode": "6056",
   "property_type": "house", "price_text": "Offers over $549,000",
   "bedrooms": 4, "bathrooms": 2, "car_spaces": 2, "land_size_sqm": 620,
   "building_size_sqm": null, "strata_annual": null, "council_annual": null,
   "days_on_market": null, "headline": "",
   "description": "Currently leased at $620 per week", "source": "agent-websearch"}
]}
```

Aim for at least 60 candidate listings before ranking, and stop at ~150.

## 4. Improve rent forecasts

Run the `refresh-rents` skill for every suburb in your candidate list that has no
row in `data/suburb_stats.csv` (at most 25 suburbs per run). Better rent data
changes rankings more than anything else.

## 5. Rank

```
python -m wa_scout scout --offline
```

This re-ranks the saved listings plus everything in `data/inbox/` and writes
`reports/shortlist-<timestamp>.{html,json,csv,md}`.

## 6. Report back

Show the user the markdown table the command prints (ranks 1-20), then:

- The three strongest candidates and why (cash flow, yield, serviceability, land).
- Any listing whose verdict is "Tight on servicing" or "Over budget" but is close,
  with what would change it (e.g. a lower offer, more cash, interest-only).
- Which rent estimates are low confidence (method says "Perth metro median").
- Where the full report is (`reports/...html`) and that `python -m wa_scout serve`
  opens the interactive view at http://localhost:8765.
- A one-line reminder that this is a screening tool, not financial advice, and
  that the user should verify rent with a local property manager and get
  building/pest and strata reports.

## Running on a schedule

If the user wants the scout to run daily, suggest `/loop 24h /wa-scout` in a
session, or a scheduled routine that runs this skill each morning.
