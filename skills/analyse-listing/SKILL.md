---
name: analyse-listing
description: Assess one WA property (a realestate.com.au / Domain URL or typed details) against the user's pre-approval and cash flow - rent forecast, duty, LVR/LMI, after-tax cash flow, serviceability and 10-year projection.
---

# Analyse a single listing

1. If the user gave a URL, try `python -m wa_scout analyse --url "<url>"`. If that
   fails (bot protection), WebFetch the page; if that is blocked too, WebSearch the
   address to find a syndicated copy (Domain, the agency's site). Extract price
   text, suburb, postcode, type, beds, baths, cars, land size, strata and any
   stated rent. If key details are still missing, ask the user for them.
2. Run:
   ```
   python -m wa_scout analyse --price "<price text>" --suburb "<Suburb>" --postcode 6xxx \
     --type house --beds 3 --baths 2 --cars 2 --land 600 [--strata 2400] [--rent 620] --url "<url>"
   ```
3. If the rent method is "Perth metro median", run the `refresh-rents` skill for
   that suburb and re-run step 2.
4. Present: score and verdict, rent estimate and its source, purchase structure
   (duty, cash used, loan, LVR, LMI), year-1 cash flow before and after tax,
   bank-test surplus, the household budget after buying, and years 1/5/10 of the
   projection. Finish with the pros/cons lists and what to verify before offering.
5. Offer to add it to the shortlist by saving it into `data/inbox/manual-ui.json`.

Never fabricate listing details. Screening estimates only, not financial advice.
