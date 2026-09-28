import json
import unittest
from pathlib import Path

from wa_scout.config import DEFAULT_PROFILE, ROOT, deep_merge
from wa_scout.listings import Listing
from wa_scout.rent import estimate_rent, load_baseline
from wa_scout.scoring import assess, rank_listings
from wa_scout.sources.manual import load_file


def house(**kw):
    base = dict(id="x", suburb="Midland", postcode="6056", property_type="house", price=550_000, bedrooms=4,
                bathrooms=2, car_spaces=2, land_size_sqm=600)
    base.update(kw)
    return Listing(**base)


class RentTests(unittest.TestCase):
    def test_stated_rent_wins(self):
        l = house(headline="Currently leased at $640 per week until June")
        r = estimate_rent(l, {}, [])
        self.assertEqual(r.weekly, 640)
        self.assertIn("stated", r.method)

    def test_comparables(self):
        comps = [house(id=str(i), price=p) for i, p in enumerate([600, 620, 640, 660])]
        r = estimate_rent(house(), {}, comps)
        self.assertEqual(r.weekly, 630)
        self.assertIn("comparable", r.method)

    def test_suburb_median_then_baseline(self):
        stats = {("midland", "house"): {"median_weekly_rent": "650", "source": "test", "as_of": "2026-08"}}
        self.assertEqual(estimate_rent(house(bedrooms=3, bathrooms=1), stats, []).weekly, 650)
        fallback = estimate_rent(house(), {}, [])
        self.assertLess(fallback.confidence, 0.5)
        self.assertGreater(fallback.weekly, 300)

    def test_more_bedrooms_more_rent(self):
        b = load_baseline()
        self.assertGreater(estimate_rent(house(bedrooms=5), {}, [], b).weekly, estimate_rent(house(bedrooms=3), {}, [], b).weekly)


class ScoringTests(unittest.TestCase):
    profile = deep_merge(DEFAULT_PROFILE, {"criteria": {"property_types": ["house", "townhouse", "villa"]}})

    def test_high_yield_beats_low_yield(self):
        good = assess(house(id="g", headline="leased at $700 per week"), self.profile, suburb_stats={}, comps=[])
        poor = assess(house(id="p", headline="leased at $420 per week"), self.profile, suburb_stats={}, comps=[])
        self.assertGreater(good.score, poor.score)

    def test_over_budget_capped(self):
        a = assess(house(price=2_000_000), self.profile, suburb_stats={}, comps=[])
        self.assertEqual(a.verdict, "Over budget")
        self.assertLessEqual(a.score, 20)

    def test_rank_sample_listings(self):
        listings = load_file(ROOT / "data" / "sample" / "sample_listings.json")
        result = rank_listings(listings, self.profile)
        top = result["top"]
        self.assertTrue(0 < len(top) <= 20)
        self.assertEqual([a.rank for a in top], list(range(1, len(top) + 1)))
        self.assertEqual(sorted((a.score for a in top), reverse=True), [a.score for a in top])
        json.dumps([a.to_dict() for a in top])  # serialisable


if __name__ == "__main__":
    unittest.main()
