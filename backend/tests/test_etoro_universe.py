import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import (
    ALL_PROVIDERS,
    PROVIDER_ETORO,
    AppConfig,
    _empty_universe,
    _normalize_universe_payload,
)

PE = PROVIDER_ETORO


class UniversePlumbingTests(unittest.TestCase):
    def test_etoro_in_all_providers(self):
        self.assertIn(PROVIDER_ETORO, ALL_PROVIDERS)

    def test_empty_universe_has_etoro(self):
        u = _empty_universe()
        self.assertIn(PROVIDER_ETORO, u)
        self.assertEqual(u[PROVIDER_ETORO], {"STOCK": [], "CRYPTO": []})

    def test_normalize_reads_etoro_entry(self):
        norm = _normalize_universe_payload({"etoro": {"STOCK": ["aapl"], "CRYPTO": ["btc"]}})
        self.assertEqual(norm[PROVIDER_ETORO]["STOCK"], ["AAPL"])
        self.assertEqual(norm[PROVIDER_ETORO]["CRYPTO"], ["BTC"])


class EtoroUniverseAdminTests(unittest.TestCase):
    def setUp(self):
        from services import universe_admin
        self.universe_admin = universe_admin
        self.config = AppConfig(
            openai_api_key="k", 
            etoro_api_key="a", etoro_user_key="b",
        )

    def test_etoro_crypto_symbol_keeps_native_form(self):
        sym = self.universe_admin._normalize_symbol("btc", "etoro", "CRYPTO", self.config)
        self.assertEqual(sym, "BTC")

    def test_etoro_category_accepts_stock_crypto(self):
        self.assertEqual(self.universe_admin._normalize_category("etoro", "crypto"), "CRYPTO")
        self.assertEqual(self.universe_admin._normalize_category("etoro", "stock"), "STOCK")

    def test_etoro_provider_accepted(self):
        self.assertEqual(self.universe_admin._normalize_provider("etoro"), "etoro")


class CheapPrefilterHelperTests(unittest.TestCase):
    def _manager(self):
        from services.universe_manager import UniverseManager
        config = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
            etoro_account_type="demo", weekly_universe_stocks=2, weekly_universe_crypto=2,
        )
        gpt = Mock()
        broker = Mock()
        return UniverseManager(config, logging.getLogger("t"), {PE: broker}, gpt), broker

    def test_is_dated_future(self):
        from services.universe_manager import UniverseManager
        for sym in ("BTC.MAY26", "BTC.JUN26", "ETH.DEC25"):
            self.assertTrue(UniverseManager._is_dated_future(sym), sym)
        for sym in ("ETH.SPOT", "HYPE", "JTO", "BTC", "BTC.X"):
            self.assertFalse(UniverseManager._is_dated_future(sym), sym)

    def test_asset_name_handles_dict_and_object(self):
        from services.universe_manager import UniverseManager
        self.assertEqual(UniverseManager._asset_name({"name": "Apple ETF"}), "apple etf")
        obj = Mock()
        obj.name = "Apple Inc"
        self.assertEqual(UniverseManager._asset_name(obj), "apple inc")

    def test_cheap_score_rewards_liquidity_and_size(self):
        manager, _ = self._manager()
        big = manager._cheap_prefilter_score({"market_cap": 1e12, "dollar_volume": 1e9})
        small = manager._cheap_prefilter_score({"market_cap": 3e8, "dollar_volume": 1e5})
        self.assertGreater(big, small)

    def test_cheap_score_rewards_analyst_consensus(self):
        manager, _ = self._manager()
        base = {"market_cap": 5e9, "dollar_volume": 2e7, "analyst_count": 15, "analyst_upside": 20.0}
        buy = manager._cheap_prefilter_score({**base, "analyst_consensus": "StrongBuy"})
        sell = manager._cheap_prefilter_score({**base, "analyst_consensus": "Sell"})
        self.assertGreater(buy, sell)

    def test_cheap_score_penalizes_daily_spike(self):
        manager, _ = self._manager()
        base = {"market_cap": 5e9, "dollar_volume": 2e7}
        calm = manager._cheap_prefilter_score({**base, "price_change_1d": 0.0})
        spiky = manager._cheap_prefilter_score({**base, "price_change_1d": 50.0})
        self.assertGreater(calm, spiky)

    def test_dedupe_by_isin_merges_variants(self):
        manager, _ = self._manager()
        canonical = self._stock("NVDA", isin="US67", pop=2, consensus="StrongBuy", upside=50.0, analysts=30)
        rth = self._stock("NVDA.RTH", isin="US67", pop=1043, consensus=None, upside=None, analysts=0)
        out = manager._dedupe_by_isin([canonical, rth])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbol"], "NVDA.RTH")             # most popular variant kept
        self.assertEqual(out[0]["analyst_consensus"], "StrongBuy")  # back-filled from sibling
        self.assertEqual(out[0]["analyst_count"], 30)

    def test_dedupe_by_isin_passes_through_empty_isin(self):
        manager, _ = self._manager()
        out = manager._dedupe_by_isin([self._crypto("BTC"), self._crypto("ETH")])
        self.assertEqual({r["symbol"] for r in out}, {"BTC", "ETH"})

    def _stock(self, symbol, country="US", market_cap=5e9, dollar_volume=2e7, pop=1000,
               name="Co", tradable=True, delisted=False, consensus="Buy", upside=10.0,
               analysts=10, isin=None):
        return {
            "symbol": symbol, "name": name, "isin": isin if isin is not None else symbol,
            "tradable": tradable, "delisted": delisted, "country_code": country,
            "market_cap": market_cap, "dollar_volume": dollar_volume, "popularity": pop,
            "instrument_type": "Stocks", "analyst_consensus": consensus,
            "analyst_upside": upside, "analyst_count": analysts,
            "revenue_growth": 10.0, "net_margin": 15.0,
            "price_change_1d": 0.0, "price_change_1m": 0.0,
            "price_change_3m": 0.0, "price_change_6m": 0.0,
        }

    def _crypto(self, symbol, pop=1000, itype="Crypto", tradable=True, market_cap=5e8):
        return {
            "symbol": symbol, "name": symbol, "isin": "", "tradable": tradable, "delisted": False,
            "country_code": "", "market_cap": market_cap, "dollar_volume": 1e6, "popularity": pop,
            "instrument_type": itype, "analyst_consensus": None, "analyst_upside": None,
            "analyst_count": 0, "revenue_growth": None, "net_margin": None,
            "price_change_1d": 0.0, "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0,
        }

    def test_passes_cheap_filter_stock_rules(self):
        manager, _ = self._manager()
        self.assertTrue(manager._passes_cheap_filter("STOCK", self._stock("AAPL")))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", country="CN")))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", market_cap=1e8)))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", dollar_volume=1e3)))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", tradable=False)))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", name="Big Index Fund")))

    def test_passes_cheap_filter_stock_allows_unknown_fundamentals(self):
        """Popularity-ranked search candidates carry no market_cap/country (the
        instruments lookup exposes identity only), so unknown fundamentals must
        pass the cheap filter — popularity already pre-qualified them. Values
        that ARE present and below threshold still reject.
        """
        manager, _ = self._manager()
        self.assertTrue(
            manager._passes_cheap_filter(
                "STOCK", self._stock("AAPL", country="", market_cap=None, dollar_volume=None)
            )
        )
        # present-but-low market cap is still rejected
        self.assertFalse(
            manager._passes_cheap_filter("STOCK", self._stock("X", country="", market_cap=1e8))
        )
        # a known non-target country is still rejected
        self.assertFalse(
            manager._passes_cheap_filter("STOCK", self._stock("X", country="CN", market_cap=None))
        )

    def test_passes_cheap_filter_crypto_rules(self):
        manager, _ = self._manager()
        self.assertTrue(manager._passes_cheap_filter("CRYPTO", self._crypto("ETH.SPOT")))
        self.assertTrue(manager._passes_cheap_filter("CRYPTO", self._crypto("HYPE")))
        self.assertFalse(manager._passes_cheap_filter("CRYPTO", self._crypto("BTC.MAY26")))
        self.assertFalse(manager._passes_cheap_filter("CRYPTO", self._crypto("X", itype="Crypto Futures")))
        self.assertFalse(manager._passes_cheap_filter("CRYPTO", self._crypto("TINY", market_cap=1e6)))

    def test_build_cheap_shortlist_stock_caps_and_filters(self):
        manager, broker = self._manager()
        manager.config.universe_stock_shortlist = 2
        broker.discover_instruments.return_value = [
            self._stock("AAA", dollar_volume=1e6),
            self._stock("BBB", dollar_volume=9e8),
            self._stock("CCC", dollar_volume=5e8),
            self._stock("FOREIGN", country="CN", dollar_volume=9e9),
        ]
        shortlist = manager._build_cheap_shortlist(broker, "STOCK", [])
        symbols = [a["symbol"] for a in shortlist]
        self.assertEqual(len(shortlist), 2)
        self.assertEqual(symbols, ["BBB", "CCC"])   # ranked by liquidity, capped
        self.assertNotIn("FOREIGN", symbols)         # wrong country filtered out

    def test_build_cheap_shortlist_stock_allows_missing_discover_volume(self):
        manager, broker = self._manager()
        broker.discover_instruments.return_value = [
            self._stock("AAPL", dollar_volume=None, market_cap=3e12),
        ]
        shortlist = manager._build_cheap_shortlist(broker, "STOCK", [])
        self.assertEqual([a["symbol"] for a in shortlist], ["AAPL"])

    def test_build_cheap_shortlist_pins_preferred(self):
        manager, broker = self._manager()
        manager.config.universe_stock_shortlist = 2
        broker.discover_instruments.return_value = [
            self._stock("AAA", dollar_volume=9e8),
            self._stock("BBB", dollar_volume=8e8),
            self._stock("KEEP", dollar_volume=1e6),
        ]
        shortlist = manager._build_cheap_shortlist(broker, "STOCK", ["KEEP"])
        symbols = [a["symbol"] for a in shortlist]
        self.assertEqual(len(shortlist), 2)        # limit=2: 1 pinned + 1 top-scored
        self.assertEqual(symbols[0], "KEEP")       # pinned symbol comes first
        self.assertIn("AAA", symbols)              # highest-liquidity pool survivor

    def test_build_cheap_shortlist_crypto_drops_futures(self):
        manager, broker = self._manager()
        manager.config.universe_crypto_shortlist = 10
        broker.discover_instruments.return_value = [
            self._crypto("ETH.SPOT", pop=100),
            self._crypto("BTC.MAY26", pop=99999),
            self._crypto("HYPE", pop=50),
        ]
        shortlist = manager._build_cheap_shortlist(broker, "CRYPTO", [])
        symbols = [a["symbol"] for a in shortlist]
        self.assertIn("ETH.SPOT", symbols)
        self.assertIn("HYPE", symbols)
        self.assertNotIn("BTC.MAY26", symbols)


class SelectEtoroUniverseWiringTests(unittest.TestCase):
    def _manager(self, broker):
        from services.universe_manager import UniverseManager
        config = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
            etoro_account_type="demo", weekly_universe_stocks=1, weekly_universe_crypto=1,
            universe_stock_shortlist=5, universe_crypto_shortlist=5,
        )
        gpt = Mock()
        gpt.request_universe_symbol_dossier.side_effect = Exception("no gpt")
        gpt.request_universe_final_selection_from_dossiers.side_effect = Exception("no gpt")
        return UniverseManager(config, logging.getLogger("t"), {PE: broker}, gpt)

    def _empty_current(self):
        return {PE: {"STOCK": [], "CRYPTO": []}}

    def _stock_row(self, symbol, **over):
        row = {
            "symbol": symbol, "name": symbol, "isin": symbol, "tradable": True, "delisted": False,
            "country_code": "US", "market_cap": 3e12, "dollar_volume": 1e9, "popularity": 9000,
            "instrument_type": "Stocks", "analyst_consensus": "Buy", "analyst_upside": 10.0,
            "analyst_count": 20, "revenue_growth": 10.0, "net_margin": 20.0,
            "price_change_1d": 0.0, "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0,
        }
        row.update(over)
        return row

    def _crypto_row(self, symbol, **over):
        row = {
            "symbol": symbol, "name": symbol, "isin": "", "tradable": True, "delisted": False,
            "country_code": "", "market_cap": 2e11, "dollar_volume": 1e8, "popularity": 9000,
            "instrument_type": "Crypto", "analyst_consensus": None, "analyst_upside": None,
            "analyst_count": 0, "revenue_growth": None, "net_margin": None,
            "price_change_1d": 0.0, "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0,
        }
        row.update(over)
        return row

    def test_uses_discover_shortlist_when_available(self):
        broker = Mock()
        broker.discover_instruments.side_effect = lambda cat: (
            [self._stock_row("AAPL")] if cat == "STOCK" else [self._crypto_row("ETH.SPOT")]
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._empty_current())
        broker.list_assets.assert_not_called()
        self.assertEqual(result["STOCK"], ["AAPL"])
        self.assertEqual(result["CRYPTO"], ["ETH.SPOT"])

    def _current(self, stock, crypto):
        return {PE: {"STOCK": list(stock), "CRYPTO": list(crypto)}}

    def test_keeps_previous_universe_when_discover_raises(self):
        """A discovery error (e.g. eToro API down) must preserve the previous
        universe rather than wipe it — there is no legacy full-scan fallback."""
        broker = Mock()
        broker.discover_instruments.side_effect = Exception("discover down")
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._current(["OLDS"], ["OLDC"]))
        self.assertEqual(result["STOCK"], ["OLDS"])
        self.assertEqual(result["CRYPTO"], ["OLDC"])

    def test_keeps_previous_universe_when_discover_empty(self):
        broker = Mock()
        broker.discover_instruments.return_value = []
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._current(["OLDS"], ["OLDC"]))
        self.assertEqual(result["STOCK"], ["OLDS"])
        self.assertEqual(result["CRYPTO"], ["OLDC"])

    def test_keeps_previous_per_category_when_one_empty(self):
        broker = Mock()
        broker.discover_instruments.side_effect = lambda cat: (
            [self._stock_row("AAPL")] if cat == "STOCK" else []  # crypto discovery empty
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._current([], ["OLDC"]))
        self.assertEqual(result["STOCK"], ["AAPL"])    # refreshed from discovery
        self.assertEqual(result["CRYPTO"], ["OLDC"])    # kept previous (no candidates)


class EtfAllowlistTests(unittest.TestCase):
    def _manager(self, etfs):
        from services.universe_manager import UniverseManager
        config = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
            etoro_account_type="demo", universe_etf_symbols=tuple(etfs),
        )
        broker = Mock()
        broker.instrument_id_for_symbol.return_value = 3000
        return UniverseManager(config, logging.getLogger("t"), {PE: broker}, Mock()), broker

    def test_injects_allowlist_etfs_as_stock(self):
        m, _ = self._manager(["SPY", "QQQ"])
        self.assertEqual(m._inject_etf_allowlist(["AAPL"]), ["AAPL", "SPY", "QQQ"])

    def test_dedupes_already_present(self):
        m, _ = self._manager(["SPY", "QQQ"])
        self.assertEqual(m._inject_etf_allowlist(["SPY"]), ["SPY", "QQQ"])

    def test_skips_unresolvable_etf(self):
        m, broker = self._manager(["SPY", "NOPE"])
        broker.instrument_id_for_symbol.side_effect = lambda s: None if s == "NOPE" else 3000
        self.assertEqual(m._inject_etf_allowlist([]), ["SPY"])

    def test_empty_allowlist_is_noop(self):
        m, _ = self._manager([])
        self.assertEqual(m._inject_etf_allowlist(["AAPL"]), ["AAPL"])


class UniverseMetadataQuoteTests(unittest.TestCase):
    """get_universe_with_metadata should batch quotes via the broker's rates API."""

    def setUp(self):
        from unittest.mock import patch
        from services import universe_admin
        self.universe_admin = universe_admin
        self._patch = patch.object(
            universe_admin,
            "read_universe_file",
            return_value={PE: {"STOCK": ["AAPL", "MSFT"], "CRYPTO": ["BTC"]}},
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _batch_broker(self):
        broker = Mock(spec=["instrument_id_for_symbol", "get_rates_by_instruments"])
        ids = {"AAPL": 1, "MSFT": 2, "BTC": 3}
        broker.instrument_id_for_symbol.side_effect = lambda s: ids.get(s)
        broker.get_rates_by_instruments.return_value = {
            1: {"bid": 100.0, "ask": 101.0, "lastExecution": 100.5},
            2: {"bid": 200.0, "ask": 201.0, "lastExecution": None},
            3: {"bid": 60000.0, "ask": 60010.0, "lastExecution": 60005.0},
        }
        return broker

    def test_batches_into_single_rates_call(self):
        broker = self._batch_broker()
        out = self.universe_admin.get_universe_with_metadata({PE: broker}, logging.getLogger("t"))
        # One batched GET total — not one per symbol.
        broker.get_rates_by_instruments.assert_called_once()
        ids_arg = sorted(broker.get_rates_by_instruments.call_args[0][0])
        self.assertEqual(ids_arg, [1, 2, 3])

    def test_prices_decorated_with_last_ask_bid_preference(self):
        broker = self._batch_broker()
        out = self.universe_admin.get_universe_with_metadata({PE: broker}, logging.getLogger("t"))
        stock = {e["symbol"]: e for e in out[PE]["STOCK"]}
        self.assertEqual(stock["AAPL"]["last_price"], 100.5)   # lastExecution wins
        self.assertEqual(stock["MSFT"]["last_price"], 201.0)   # falls back to ask
        self.assertIsNone(stock["AAPL"]["quote_error"])
        self.assertEqual(out[PE]["CRYPTO"][0]["last_price"], 60005.0)

    def test_unresolved_symbol_reports_error_without_price(self):
        broker = self._batch_broker()
        broker.instrument_id_for_symbol.side_effect = lambda s: None if s == "MSFT" else {"AAPL": 1, "BTC": 3}.get(s)
        out = self.universe_admin.get_universe_with_metadata({PE: broker}, logging.getLogger("t"))
        msft = next(e for e in out[PE]["STOCK"] if e["symbol"] == "MSFT")
        self.assertIsNone(msft["last_price"])
        self.assertEqual(msft["quote_error"], "unknown instrument")
        # The unresolved id must not be sent to the rates batch.
        self.assertEqual(sorted(broker.get_rates_by_instruments.call_args[0][0]), [1, 3])

    def test_batch_rates_failure_degrades_gracefully(self):
        broker = self._batch_broker()
        broker.get_rates_by_instruments.side_effect = RuntimeError("etoro 500")
        out = self.universe_admin.get_universe_with_metadata({PE: broker}, logging.getLogger("t"))
        aapl = next(e for e in out[PE]["STOCK"] if e["symbol"] == "AAPL")
        self.assertIsNone(aapl["last_price"])
        self.assertEqual(aapl["quote_error"], "etoro 500")

    def test_falls_back_to_per_symbol_when_no_batch_api(self):
        broker = Mock(spec=["get_latest_price"])
        broker.get_latest_price.side_effect = lambda s, c: {"AAPL": 1.0, "MSFT": 2.0, "BTC": 3.0}[s]
        out = self.universe_admin.get_universe_with_metadata({PE: broker}, logging.getLogger("t"))
        stock = {e["symbol"]: e["last_price"] for e in out[PE]["STOCK"]}
        self.assertEqual(stock, {"AAPL": 1.0, "MSFT": 2.0})
        self.assertEqual(broker.get_latest_price.call_count, 3)

    def test_missing_broker_marks_not_configured(self):
        out = self.universe_admin.get_universe_with_metadata({}, logging.getLogger("t"))
        aapl = next(e for e in out[PE]["STOCK"] if e["symbol"] == "AAPL")
        self.assertIsNone(aapl["last_price"])
        self.assertIn("not configured", aapl["quote_error"])


class CryptoReliabilityGateTests(unittest.TestCase):
    """Hard liquidity + 1-month volatility gate that screens out unreliable crypto."""

    def _manager(self, **overrides):
        from services.universe_manager import UniverseManager
        kwargs = dict(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
            etoro_account_type="demo", weekly_universe_stocks=2, weekly_universe_crypto=2,
            universe_crypto_min_dollar_volume=3_000_000.0,
            universe_crypto_max_volatility_1m_pct=60.0,
        )
        kwargs.update(overrides)
        config = AppConfig(**kwargs)
        return UniverseManager(config, logging.getLogger("t"), {PE: Mock()}, Mock())

    @staticmethod
    def _bars(daily_step_pct: float, count: int = 22, volume: float = 100.0):
        """Synthetic bars where each close moves by +/- daily_step_pct alternately."""
        bars = []
        price = 100.0
        for i in range(count):
            price *= 1.0 + (daily_step_pct / 100.0 if i % 2 == 0 else -daily_step_pct / 100.0)
            bars.append({"timestamp": f"2026-01-{i + 1:02d}", "close": round(price, 6), "volume": volume})
        return bars

    def test_metrics_expose_one_month_volatility_below_annualized(self):
        manager = self._manager()
        metrics = manager._compute_market_metrics(self._bars(5.0), "CRYPTO")
        self.assertIsNotNone(metrics["realized_volatility_1m_pct"])
        self.assertIsNotNone(metrics["realized_volatility_20d_pct"])
        # 1-month figure must be materially smaller than the annualized one.
        self.assertLess(metrics["realized_volatility_1m_pct"], metrics["realized_volatility_20d_pct"])

    def test_gate_passes_liquid_calm_crypto(self):
        manager = self._manager()
        asset = {"bar_count": 90, "avg_dollar_volume_20d": 8_000_000.0, "realized_volatility_1m_pct": 25.0}
        self.assertTrue(manager._passes_liquidity_prefilter("CRYPTO", asset))

    def test_gate_blocks_thin_volume(self):
        manager = self._manager()
        asset = {"bar_count": 90, "avg_dollar_volume_20d": 1_000_000.0, "realized_volatility_1m_pct": 25.0}
        self.assertFalse(manager._passes_liquidity_prefilter("CRYPTO", asset))

    def test_gate_blocks_excessive_one_month_volatility(self):
        manager = self._manager()
        asset = {"bar_count": 90, "avg_dollar_volume_20d": 8_000_000.0, "realized_volatility_1m_pct": 95.0}
        self.assertFalse(manager._passes_liquidity_prefilter("CRYPTO", asset))

    def test_gate_passes_when_volatility_metric_missing(self):
        manager = self._manager()
        asset = {"bar_count": 90, "avg_dollar_volume_20d": 8_000_000.0, "realized_volatility_1m_pct": None}
        self.assertTrue(manager._passes_liquidity_prefilter("CRYPTO", asset))

    def test_vol_cap_disabled_when_zero(self):
        manager = self._manager(universe_crypto_max_volatility_1m_pct=0.0)
        asset = {"bar_count": 90, "avg_dollar_volume_20d": 8_000_000.0, "realized_volatility_1m_pct": 300.0}
        self.assertTrue(manager._passes_liquidity_prefilter("CRYPTO", asset))


if __name__ == "__main__":
    unittest.main()
