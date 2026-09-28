import unittest

from wa_scout import finance
from wa_scout.config import DEFAULT_PROFILE, deep_merge


class DutyAndTaxTests(unittest.TestCase):
    def test_wa_transfer_duty_brackets(self):
        self.assertEqual(finance.wa_transfer_duty(100_000), 1_900)
        self.assertEqual(finance.wa_transfer_duty(360_000), 11_115)
        self.assertAlmostEqual(finance.wa_transfer_duty(725_000), 28_452.5, places=1)
        self.assertAlmostEqual(finance.wa_transfer_duty(600_000), 11_115 + 240_000 * 0.0475, places=2)
        self.assertAlmostEqual(finance.wa_transfer_duty(900_000), 28_453 + 175_000 * 0.0515, places=2)

    def test_land_tax(self):
        self.assertEqual(finance.wa_land_tax(250_000), 0)
        # 350k: $300 flat + MRIT 0.14% of 50k
        self.assertAlmostEqual(finance.wa_land_tax(350_000), 300 + 70, places=2)
        self.assertAlmostEqual(finance.wa_land_tax(500_000, metro=False), 300 + 80_000 * 0.0025, places=2)

    def test_income_tax(self):
        self.assertEqual(finance.income_tax(18_000), 0)
        # 120k: 4,020 + 30% of 75k + 2% Medicare
        self.assertAlmostEqual(finance.income_tax(120_000), 4_020 + 22_500 + 2_400, places=2)
        self.assertAlmostEqual(finance.income_tax(200_000), 51_370 + 4_500 + 4_000, places=2)

    def test_repayment(self):
        # Standard amortisation check: $500k, 6%, 30y ~= $2,997.75
        self.assertAlmostEqual(finance.monthly_repayment(500_000, 6.0, 30), 2997.75, places=1)
        self.assertEqual(finance.interest_only_repayment(500_000, 6.0), 2500)


class PurchaseTests(unittest.TestCase):
    def setUp(self):
        self.profile = deep_merge(DEFAULT_PROFILE, {"preapproval": {"loan_amount": 600_000, "cash_available": 120_000, "cash_buffer": 0}})

    def test_structure_within_preapproval(self):
        p = finance.structure_purchase(500_000, self.profile)
        self.assertTrue(p.within_preapproval)
        self.assertAlmostEqual(p.cash_used + p.base_loan, 500_000 + p.duty + p.other_costs, places=1)
        self.assertGreater(p.lmi, 0)  # LVR > 80%

    def test_max_price_is_boundary(self):
        m = finance.max_purchase_price(self.profile)
        self.assertTrue(finance.structure_purchase(m - 1_000, self.profile).within_preapproval)
        self.assertFalse(finance.structure_purchase(m + 5_000, self.profile).within_preapproval)

    def test_negative_gearing_reduces_loss(self):
        cf = finance.property_cash_flow(600_000, 450, 540_000, self.profile)
        self.assertLess(cf.pre_tax_annual, 0)
        self.assertGreater(cf.tax_effect_annual, 0)
        self.assertGreater(cf.after_tax_annual, cf.pre_tax_annual)

    def test_serviceability_worse_with_bigger_loan(self):
        small = finance.serviceability(self.profile, 300_000, 500)
        big = finance.serviceability(self.profile, 700_000, 500)
        self.assertGreater(small.surplus_monthly, big.surplus_monthly)

    def test_forecast_length_and_growth(self):
        rows = finance.forecast(600_000, 600, 540_000, 90_000, self.profile)
        self.assertEqual(len(rows), self.profile["assumptions"]["forecast_years"])
        self.assertGreater(rows[-1]["property_value"], 600_000)
        self.assertLess(rows[-1]["loan_balance"], 540_000)


if __name__ == "__main__":
    unittest.main()
