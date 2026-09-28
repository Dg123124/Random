---
name: refresh-rents
description: Research current median weekly rents (and median sale prices) for WA suburbs from free public sources and record them in data/suburb_stats.csv so WA Property Scout's rent forecasts are suburb-specific.
---

# Refresh suburb rent data

Input: a list of suburbs (from the user, or suburbs in the latest shortlist whose
rent method says "Perth metro median").

For each suburb and property class (house, unit):

1. WebSearch for recent figures, for example:
   - `<Suburb> WA median rent house REIWA`
   - `<Suburb> WA 6xxx suburb profile median rent realestate.com.au`
   - `SQM Research weekly rents postcode 6xxx`
   Prefer REIWA suburb profiles, realestate.com.au / Domain suburb profiles, SQM
   Research and WA Department of Communities rental data. Use the most recent
   figure (last 12 months). Record the median sale price too if it is shown.
2. If a page is fetchable, WebFetch it to confirm the number. If sources disagree,
   use the most recent, and prefer REIWA for WA.
3. Update `data/suburb_stats.csv` (one row per suburb + class; replace an older
   row rather than duplicating):
   `suburb,postcode,property_type,median_weekly_rent,median_price,source,as_of`
   e.g. `Midland,6056,house,650,640000,REIWA suburb profile,2026-08`

Rules: only record numbers you actually saw in a source, with the source name and
month. Leave a column blank rather than guess. Tell the user which suburbs you
updated and which you could not find.

Optionally, if rental listings for the suburb are visible (realestate.com.au/rent,
Domain rent search), add 3-10 comparable rentals to `data/rental_comps.json` under
`listings` with `suburb`, `postcode`, `property_type`, `bedrooms`, `bathrooms`,
`car_spaces`, `weekly_rent`, `url`, `collected`. Comparable rentals give the
highest-confidence estimates.
