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
        up = [10, 11, 12.1, 13.31, 14.641, 16.105, 17.716]
        hist = {"AAA": _bars(up), "BBB": _bars(up)}
        svc = self._svc_with_history(hist)
        vols, returns_map, _ = svc._symbol_stats([("AAA", "STOCK"), ("BBB", "STOCK")])
        sigma_p = svc._portfolio_vol({"AAA": 0.5, "BBB": 0.5}, vols, returns_map)
        self.assertAlmostEqual(sigma_p, vols["AAA"], places=4)

    def test_portfolio_vol_diversification_reduces(self):
        up = [10, 11, 12.1, 13.31, 14.641, 16.105, 17.716]
        down = list(reversed(up))
        hist = {"AAA": _bars(up), "BBB": _bars(down)}
        svc = self._svc_with_history(hist)
        vols, returns_map, _ = svc._symbol_stats([("AAA", "STOCK"), ("BBB", "STOCK")])
        sigma_p = svc._portfolio_vol({"AAA": 0.5, "BBB": 0.5}, vols, returns_map)
        self.assertLess(sigma_p, vols["AAA"])


if __name__ == "__main__":
    unittest.main()
