---
name: setup-profile
description: Interview the user about their pre-approval, income, expenses, current mortgage and target property (type, size, bedrooms, bathrooms, car spaces, suburbs) and save it to profile.json for WA Property Scout.
---

# Set up your investor profile

Collect the details below conversationally (group questions, 3-5 at a time) and
write them to `profile.json` at the repo root. Use `profile.example.json` for the
exact shape. Anything the user skips keeps the default in `wa_scout/config.py`.

1. **Pre-approval**: approved loan amount, lender rate, loan term, P&I or interest
   only, cash available for deposit and costs, cash they want kept in reserve,
   first home buyer (yes/no).
2. **Income**: gross yearly salary for each applicant, other taxable income, rent
   already received from other investment properties (weekly).
3. **Expenses**: monthly living costs, other monthly loan repayments (car,
   personal, HECS, BNPL), total credit card limits, number of dependants.
4. **Current mortgage**: balance, rate, monthly repayment, property value, and
   whether it is their home.
5. **What they want**: property types (house, townhouse, villa, duplex, unit,
   apartment, land), price range, min/max bedrooms, min bathrooms, min car
   spaces, land size range (m²), minimum floor area, suburbs to include or avoid,
   how many to shortlist (default 20).
6. **Assumptions** (offer defaults, let them change): rent growth 4%, capital
   growth 5%, vacancy 2 weeks, management 8.25%, forecast 10 years.

After saving, run `python -m wa_scout budget` and explain the max purchase price,
cash needed, and whether the bank-style serviceability test passes before rent.
If it fails, say what drives it (DTI above 6, living costs vs HEM, existing
mortgage at the buffered rate) so the user can correct inputs.

Do not echo the full profile back into chat; summarise it.
