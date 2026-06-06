import logging
import math
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig
from services.portfolio_risk import PortfolioRiskService


def _bars(closes, start_ts=1):
    # ascending daily bars; timestamps as zero-padded ints so string sort == time order
    return [{"timestamp": f"{start_ts + i:04d}", "close": c} for i, c in enumerate(closes)]


def _service():
    cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
    return PortfolioRiskService(cfg, logging.getLogger("t"), history_provider=lambda s, l: [])


class StatHelperTests(unittest.TestCase):
    def test_closes_and_returns_by_ts(self):
        svc = _service()
        closes = svc._closes_by_ts(_bars([10.0, 11.0, 0.0, 12.0]))
        self.assertEqual(closes["0001"], 10.0)
        self.assertNotIn("0003", closes)  # close 0.0 dropped
        rets = svc._returns_by_ts({"0001": 10.0, "0002": 11.0})
        self.assertAlmostEqual(rets["0002"], math.log(11.0 / 10.0))

    def test_annualized_vol(self):
        svc = _service()
        rets = [0.01, -0.01, 0.02, -0.02, 0.0, 0.01]
        vol = svc._annualized_vol(rets, "STOCK")
        self.assertIsNotNone(vol)
        self.assertGreater(vol, 0.0)
        self.assertGreater(svc._annualized_vol(rets, "CRYPTO"), vol)
        self.assertIsNone(svc._annualized_vol([0.01], "STOCK"))

    def test_pearson_alignment(self):
        svc = _service()
        a = {"01": 0.1, "02": -0.1, "03": 0.2, "04": -0.2}
        same = {"01": 0.1, "02": -0.1, "03": 0.2, "04": -0.2}
        opp = {"01": -0.1, "02": 0.1, "03": -0.2, "04": 0.2}
        self.assertAlmostEqual(svc._pearson(a, same), 1.0, places=6)
        self.assertAlmostEqual(svc._pearson(a, opp), -1.0, places=6)
        self.assertIsNone(svc._pearson(a, {"01": 0.1}))  # <3 overlap


class PortfolioVolTests(unittest.TestCase):
    def _svc_with_history(self, history: dict):
        cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        return PortfolioRiskService(cfg, logging.getLogger("t"),
                                    history_provider=lambda s, l: history.get(s, []))

    def test_symbol_vols_and_fallback(self):
        hist = {"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3, 10.1])}
        svc = self._svc_with_history(hist)
        vols, returns_map, low_conf = svc._symbol_stats([("AAA", "STOCK"), ("ZZZ", "STOCK")])
        self.assertGreater(vols["AAA"], 0.0)
        self.assertEqual(vols["ZZZ"], svc.config.risk_default_stock_vol)
        self.assertTrue(low_conf)
        self.assertIn("AAA", returns_map)

    def test_portfolio_vol_correlation_effect(self):
        # a series with meaningful volatility (not near-zero) so shrinkage shows
        series = [10, 11, 9.5, 12, 9, 12.5, 10.5]
        hist = {"AAA": _bars(series), "BBB": _bars(series)}
        svc = self._svc_with_history(hist)
        vols, returns_map, _ = svc._symbol_stats([("AAA", "STOCK"), ("BBB", "STOCK")])
        sigma_p = svc._portfolio_vol({"AAA": 0.5, "BBB": 0.5}, vols, returns_map)
        lam = svc.config.risk_corr_shrinkage
        rho = lam * 1.0 + (1.0 - lam) * 0.5  # identical series -> sample corr 1.0, shrunk
        expected = math.sqrt(0.5 + 0.5 * rho) * vols["AAA"]
        self.assertAlmostEqual(sigma_p, expected, places=6)
        # correlated pair is riskier than the fully-diversified floor
        self.assertGreater(sigma_p, 0.0)

    def test_portfolio_vol_diversification_reduces(self):
        up = [10, 11, 12.1, 13.31, 14.641, 16.105, 17.716]
        down = list(reversed(up))
        hist = {"AAA": _bars(up), "BBB": _bars(down)}
        svc = self._svc_with_history(hist)
        vols, returns_map, _ = svc._symbol_stats([("AAA", "STOCK"), ("BBB", "STOCK")])
        sigma_p = svc._portfolio_vol({"AAA": 0.5, "BBB": 0.5}, vols, returns_map)
        self.assertLess(sigma_p, vols["AAA"])


class AssessTests(unittest.TestCase):
    def _svc(self, history=None, **cfg_over):
        cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                        max_open_trades_stock=3, max_open_trades_crypto=3, **cfg_over)
        history = history or {}
        return PortfolioRiskService(cfg, logging.getLogger("t"),
                                    history_provider=lambda s, l: history.get(s, []))

    def test_budget_vol_mapping(self):
        svc = self._svc(risk_tolerance=1)
        self.assertAlmostEqual(svc._budget_vol(), 0.10, places=6)
        svc = self._svc(risk_tolerance=10)
        self.assertAlmostEqual(svc._budget_vol(), 0.45, places=6)

    def test_empty_portfolio(self):
        svc = self._svc()
        a = svc.assess([], equity=10_000.0)
        self.assertEqual(a.score, 0.0)
        self.assertEqual(a.exposure, 0.0)
        self.assertFalse(a.over_alert)

    def test_single_position_concentration_max(self):
        svc = self._svc(history={"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3])})
        a = svc.assess([{"symbol": "AAA", "category": "STOCK", "value": 5_000.0}], equity=10_000.0)
        self.assertEqual(a.components["concentration"], 100.0)
        self.assertEqual(a.components["correlation"], 0.0)
        self.assertAlmostEqual(a.exposure, 0.5, places=6)
        self.assertEqual(a.components["exposure"], 50.0)

    def test_correlated_vs_diversified_score(self):
        up = [10, 11, 12.1, 13.31, 14.641, 16.105, 17.716]
        down = list(reversed(up))
        corr = self._svc(history={"AAA": _bars(up), "BBB": _bars(up)})
        div = self._svc(history={"AAA": _bars(up), "BBB": _bars(down)})
        pos = [{"symbol": "AAA", "category": "STOCK", "value": 5_000.0},
               {"symbol": "BBB", "category": "STOCK", "value": 5_000.0}]
        self.assertGreater(corr.assess(pos, 10_000.0).score, div.assess(pos, 10_000.0).score)

    def test_over_thresholds_and_low_confidence(self):
        svc = self._svc(history={"AAA": _bars([10, 13, 9, 14, 8, 15, 7])},
                        risk_tolerance=1, risk_hard_threshold=10.0, risk_alert_threshold=5.0)
        a = svc.assess([{"symbol": "AAA", "category": "STOCK", "value": 9_000.0},
                        {"symbol": "ZZZ", "category": "STOCK", "value": 1_000.0}], equity=10_000.0)
        self.assertTrue(a.over_alert)
        self.assertTrue(a.over_hard)
        self.assertTrue(a.low_confidence)
        self.assertEqual(round(sum(a.per_position_risk_contribution.values())), 100)

    def test_duplicate_symbols_are_aggregated(self):
        svc = self._svc(history={"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3])})
        a = svc.assess([
            {"symbol": "AAA", "category": "STOCK", "value": 3_000.0},
            {"symbol": "AAA", "category": "STOCK", "value": 2_000.0},
        ], equity=10_000.0)
        # one effective holding -> HHI == 1 -> concentration 100; exposure 50%
        self.assertEqual(a.components["concentration"], 100.0)
        self.assertAlmostEqual(a.exposure, 0.5, places=6)

    def test_non_numeric_value_is_skipped(self):
        svc = self._svc(history={"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3])})
        a = svc.assess([
            {"symbol": "AAA", "category": "STOCK", "value": 5_000.0},
            {"symbol": "BAD", "category": "STOCK", "value": "N/A"},
        ], equity=10_000.0)
        self.assertNotIn("BAD", a.per_position_risk_contribution)
        self.assertAlmostEqual(a.exposure, 0.5, places=6)  # only AAA counts

    def test_equity_zero_with_positions_low_confidence(self):
        svc = self._svc(history={"AAA": _bars([10, 10.1, 9.9, 10.2])})
        a = svc.assess([{"symbol": "AAA", "category": "STOCK", "value": 5_000.0}], equity=0.0)
        self.assertEqual(a.score, 0.0)
        self.assertTrue(a.low_confidence)


if __name__ == "__main__":
    unittest.main()
