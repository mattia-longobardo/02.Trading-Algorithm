"""Trade / position views render in the trade's native broker currency.

Regression test for the currency-mix bug: ``MetricsService._decorate`` used
to FX-convert ``entry_price``/``take_profit``/``stop_loss`` into the dashboard
display currency (EUR) while the live price shown beside them (built by
``live_snapshot`` straight from the broker rates) stayed native (USD). Mixing
the two made open positions look like they had crossed their take-profit —
e.g. a USD "last" of 1166 sitting above a EUR-converted "TP" of 1124 — when in
a single currency they had not (1166 USD < 1298 USD). The trade engine reasons
entirely in native currency, so the per-trade views must too.
"""

import logging
import sys
import time
import unittest
from types import ModuleType

# -- stub heavy optional deps not installed in the host venv -----------------
dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

# ---------------------------------------------------------------------------

from core import fx  # noqa: E402
from core.fx import _CachedRate, _cache, _cache_lock  # noqa: E402
from core.utils import AppConfig  # noqa: E402
from services.metrics_service import MetricsService  # noqa: E402


def _make_config(**overrides) -> AppConfig:
    cfg = AppConfig(
        openai_api_key="k",
        etoro_api_key="a",
        etoro_user_key="b",
        etoro_account_type="demo",
    )
    for k, v in overrides.items():
        object.__setattr__(cfg, k, v)
    return cfg


class DecorateNativeCurrencyTests(unittest.TestCase):
    """``_decorate`` keeps monetary fields in the trade's native currency."""

    def setUp(self):
        fx.reset_cache()
        # Seed a USD->EUR rate (~the live EUR/USD inverse) that WOULD shift the
        # numbers if conversion were applied, so a green test proves it was not.
        with _cache_lock:
            _cache[("USD", "EUR")] = _CachedRate(
                rate=0.866, fetched_at=time.monotonic(), ok=True
            )
        self.metrics = MetricsService(
            _make_config(currency="EUR", account_currency="USD"),
            logging.getLogger("test"),
        )

    def tearDown(self):
        fx.reset_cache()

    def test_open_trade_fields_stay_native_usd(self):
        row = {
            "id": 1, "symbol": "LLY.RTH", "category": "STOCK", "status": "OPEN",
            "entry_price": 1178.4, "take_profit": 1298.0, "stop_loss": 1112.0,
            "current_price": 1166.4, "quantity": 31.95, "pnl": -383.0,
            "account_currency": "USD", "provider": "etoro",
        }
        out = self.metrics._decorate(row)
        # Native USD, unchanged — NOT scaled by the ~0.866 USD->EUR rate.
        self.assertAlmostEqual(out["entry_price"], 1178.4, places=4)
        self.assertAlmostEqual(out["take_profit"], 1298.0, places=4)
        self.assertAlmostEqual(out["stop_loss"], 1112.0, places=4)
        self.assertAlmostEqual(out["current_price"], 1166.4, places=4)
        self.assertEqual(out["account_currency"], "USD")

    def test_take_profit_not_falsely_crossed(self):
        # entry/current/TP must all be in the same currency so the comparison
        # the user makes by eye matches the engine: 1166 USD < 1298 USD.
        row = {
            "id": 2, "symbol": "GS.RTH", "category": "STOCK", "status": "OPEN",
            "entry_price": 1056.2, "take_profit": 1168.0, "stop_loss": 1001.0,
            "current_price": 1056.8, "quantity": 27.0, "pnl": 16.0,
            "account_currency": "USD",
        }
        out = self.metrics._decorate(row)
        self.assertLess(out["current_price"], out["take_profit"])

    def test_pnl_stays_native(self):
        row = {
            "id": 3, "symbol": "BTC", "category": "CRYPTO", "status": "OPEN",
            "entry_price": 63444.0, "take_profit": 79000.0, "stop_loss": 57800.0,
            "current_price": 64064.0, "quantity": 0.1823, "pnl": 0.0,
            "account_currency": "USD",
        }
        out = self.metrics._decorate(row)
        # unrealized PnL computed and reported in native USD.
        expected = (64064.0 - 63444.0) * 0.1823
        self.assertAlmostEqual(out["unrealized_pnl"], expected, places=2)


if __name__ == "__main__":
    unittest.main()
