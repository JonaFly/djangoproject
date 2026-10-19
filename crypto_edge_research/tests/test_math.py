import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import binance_carry as bc
import cross_venue_iv as cv
import deribit_vrp as dv
import polymarket_scan as pm
from common import bs_delta, bs_price, realized_vol, rolling_realized_vol


class TestVol(unittest.TestCase):
    def test_realized_vol_matches_formula(self):
        closes = [100, 101, 99, 102, 101.5, 103]
        r = [math.log(b / a) for a, b in zip(closes, closes[1:])]
        mu = sum(r) / len(r)
        var = sum((x - mu) ** 2 for x in r) / (len(r) - 1)
        self.assertAlmostEqual(realized_vol(closes), math.sqrt(var * 365) * 100, places=9)

    def test_rolling_window_nan_prefix(self):
        out = rolling_realized_vol([100 + i for i in range(10)], 5)
        self.assertTrue(all(math.isnan(x) for x in out[:5]) and not math.isnan(out[5]))

    def test_bs_atm_delta_and_parity(self):
        self.assertAlmostEqual(bs_delta(100, 100, 0.25, 0.5, True), 0.5, delta=0.06)
        c, p = bs_price(100, 100, 0.5, 0.6, True), bs_price(100, 100, 0.5, 0.6, False)
        self.assertAlmostEqual(c - p, 0.0, places=9)  # r = 0 put-call parity

    def test_regime_flag(self):
        self.assertEqual(dv.regime_flag({"latest_spread_volpts": 10, "dvol_percentile_1y": 50}), "DEPLOY_SHORT_VOL")
        self.assertEqual(dv.regime_flag({"latest_spread_volpts": -1, "dvol_percentile_1y": 5}), "NO_PREMIUM_STAND_ASIDE")
        self.assertEqual(dv.regime_flag({"latest_spread_volpts": 3, "dvol_percentile_1y": 50}), "THIN_PREMIUM_WAIT")

    def test_parse_instrument(self):
        exp, k, call = dv.parse_instrument("BTC-26DEC25-100000-C")
        self.assertEqual((exp.year, exp.month, exp.day, k, call), (2025, 12, 26, 100000.0, True))
        self.assertIsNone(dv.parse_instrument("BTC-PERPETUAL"))

    def test_vrp_statistics_synthetic(self):
        day = 86_400_000
        closes = [(i * day, 100.0 * (1.001 ** i)) for i in range(80)]  # near-zero realized vol
        dvol = [(i * day, 50.0) for i in range(80)]
        s = dv.vrp_statistics(dvol, closes)
        self.assertEqual(s["obs_days"], 50)
        self.assertGreater(s["mean_vrp_volpts"], 49)
        self.assertEqual(s["vrp_hit_rate"], 1.0)


class TestCarry(unittest.TestCase):
    def test_funding_annualisation(self):
        rows = [{"t": i, "rate": 0.0001} for i in range(300)]
        s = bc.funding_summary(rows)
        self.assertAlmostEqual(s["ann_30d_pct"], 10.95, places=6)
        self.assertEqual(s["negative_share"], 0.0)

    def test_dated_basis(self):
        now = datetime(2026, 10, 19, tzinfo=timezone.utc)
        b = bc.dated_basis(102.0, 100.0, now + timedelta(days=73), now)
        self.assertAlmostEqual(b["ann_basis_pct"], 10.0, places=9)

    def test_net_carry_fee_drag(self):
        # 0.3% round trip amortised over 90 days = 1.2167%/yr
        self.assertAlmostEqual(bc.net_carry(10.0, 90), 10 - 0.003 * 365 / 90 * 100, places=9)


class TestCrossVenue(unittest.TestCase):
    def test_fee_caps(self):
        self.assertAlmostEqual(cv.option_fee("binance", 10.0, 100000), 1.0)       # cap 10% of premium
        self.assertAlmostEqual(cv.option_fee("binance", 1000.0, 100000), 30.0)    # 0.03% notional
        self.assertAlmostEqual(cv.option_fee("deribit", 10.0, 100000), 1.25)      # cap 12.5%
        self.assertAlmostEqual(cv.option_fee("deribit", 1000.0, 100000), 30.0)

    def test_executable_edge_negative_when_books_overlap(self):
        self.assertLess(cv.executable_edge(500, 480, 100000, "binance", "deribit"), 0)
        self.assertGreater(cv.executable_edge(500, 600, 100000, "binance", "deribit"), 0)


class TestPolymarket(unittest.TestCase):
    def test_dutch_book(self):
        db = pm.dutch_book([[0.30, 0.32], [0.40, 0.42], [0.20, 0.22]])
        self.assertAlmostEqual(db["buy_all_yes_profit"], 1 - 0.96)
        self.assertAlmostEqual(db["sell_all_yes_profit"], 0.90 - 1)

    def test_taker_fee_formula(self):
        self.assertAlmostEqual(pm.taker_fee(0.5, "crypto"), 0.0175)   # $1.75 per 100 shares at 50c
        self.assertEqual(pm.taker_fee(0.5, "default"), 0.0)

    def test_parse_bracket(self):
        self.assertEqual(pm.parse_bracket("66-67°F"), (66.0, 67.0))
        self.assertEqual(pm.parse_bracket("60°F or below"), (-math.inf, 60.0))
        self.assertEqual(pm.parse_bracket("72°F or higher"), (72.0, math.inf))
        self.assertEqual(pm.parse_bracket("≤10°C"), (-math.inf, 10.0))
        self.assertEqual(pm.parse_bracket("68°F"), (68.0, 68.0))

    def test_bracket_probabilities_sum_to_one(self):
        members = [70.1, 71.4, 72.9, 68.0, 75.2, 71.0]
        brackets = [(-math.inf, 68), (69, 70), (71, 72), (73, 74), (75, math.inf)]
        tot = sum(pm.bracket_probability(members, lo, hi) for lo, hi in brackets)
        self.assertAlmostEqual(tot, 1.0, places=9)
        self.assertGreater(pm.bracket_probability(members, 71, 72), pm.bracket_probability(members, 75, math.inf))

    def test_longshot_yield(self):
        ev = {"title": "Will X happen?", "endDate": (datetime.now(timezone.utc) + timedelta(days=36.5)).isoformat(),
              "markets": [{"question": "Will X happen?", "bestAsk": 0.03, "bestBid": 0.02, "liquidityNum": 1000}]}
        r = pm.longshot_no_yield([ev])[0]
        self.assertAlmostEqual(r["simple_return_pct"], (1 / 0.98 - 1) * 100, places=6)
        self.assertAlmostEqual(r["ann_return_pct"], (1 / 0.98 - 1) * 1000, delta=0.2)


if __name__ == "__main__":
    unittest.main()
