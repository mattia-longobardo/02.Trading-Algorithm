import os
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig, DEFAULT_UNIVERSE_COUNTRIES, PROVIDER_ETORO, load_config


class EtoroConfigTests(unittest.TestCase):
    def test_provider_constant(self):
        self.assertEqual(PROVIDER_ETORO, "etoro")

    def test_demo_property_defaults_true(self):
        config = AppConfig(
            openai_api_key="k",
            
            
            
            etoro_api_key="app-key",
            etoro_user_key="user-key",
            etoro_account_type="demo",
        )
        self.assertTrue(config.demo)
        self.assertTrue(config.etoro_enabled)
        self.assertIn(PROVIDER_ETORO, config.active_providers())

    def test_real_account_type(self):
        config = AppConfig(
            openai_api_key="k",
            
            
            
            etoro_api_key="a",
            etoro_user_key="b",
            etoro_account_type="real",
        )
        self.assertFalse(config.demo)

    def test_load_config_reads_etoro_env(self):
        env = {
            "OPENAI_API_KEY": "o",
            "ETORO_API_KEY": "  app  ",
            "ETORO_USER_KEY": " user ",
            "ETORO_ACCOUNT_TYPE": "REAL",
            "ETORO_DEFAULT_LEVERAGE": "1",
            "ETORO_MIN_TRADE_AMOUNT": "50",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.etoro_api_key, "app")
        self.assertEqual(config.etoro_user_key, "user")
        self.assertEqual(config.etoro_account_type, "real")
        self.assertFalse(config.demo)
        self.assertEqual(config.etoro_default_leverage, 1)
        self.assertEqual(config.etoro_min_trade_amount, 50.0)

    def test_universe_defaults(self):
        config = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        self.assertEqual(config.universe_stock_shortlist, 300)
        self.assertEqual(config.universe_crypto_shortlist, 150)
        self.assertEqual(config.universe_stock_min_market_cap, 2_000_000_000.0)
        self.assertEqual(config.universe_stock_min_dollar_volume, 5_000_000.0)
        self.assertEqual(config.universe_crypto_min_market_cap, 100_000_000.0)
        self.assertIn("US", config.universe_countries)
        self.assertIn("IT", config.universe_countries)

    def test_load_config_reads_universe_env(self):
        env = {
            "OPENAI_API_KEY": "o",
            "UNIVERSE_STOCK_SHORTLIST": "120",
            "UNIVERSE_CRYPTO_SHORTLIST": "40",
            "UNIVERSE_COUNTRIES": "us, GB , de",
            "UNIVERSE_STOCK_MIN_MARKET_CAP": "5000000000",
            "UNIVERSE_STOCK_MIN_DOLLAR_VOLUME": "10000000",
            "UNIVERSE_CRYPTO_MIN_MARKET_CAP": "250000000",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.universe_stock_shortlist, 120)
        self.assertEqual(config.universe_crypto_shortlist, 40)
        self.assertEqual(config.universe_countries, ("US", "GB", "DE"))
        self.assertEqual(config.universe_stock_min_market_cap, 5_000_000_000.0)
        self.assertEqual(config.universe_stock_min_dollar_volume, 10_000_000.0)
        self.assertEqual(config.universe_crypto_min_market_cap, 250_000_000.0)

    def test_load_config_universe_countries_default_when_unset(self):
        env = {"OPENAI_API_KEY": "o"}
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.universe_countries, DEFAULT_UNIVERSE_COUNTRIES)
        self.assertEqual(config.universe_stock_shortlist, 300)

    def test_load_config_universe_countries_blank_falls_back(self):
        env = {"OPENAI_API_KEY": "o", "UNIVERSE_COUNTRIES": "  ,  "}
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.universe_countries, DEFAULT_UNIVERSE_COUNTRIES)

    def test_load_config_shortlist_floor_clamp(self):
        env = {"OPENAI_API_KEY": "o", "UNIVERSE_STOCK_SHORTLIST": "3", "UNIVERSE_CRYPTO_SHORTLIST": "0"}
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.universe_stock_shortlist, 10)
        self.assertEqual(config.universe_crypto_shortlist, 10)

    def test_risk_defaults(self):
        config = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        self.assertEqual(config.risk_weight_vol, 0.30)
        self.assertEqual(config.risk_weight_concentration, 0.30)
        self.assertEqual(config.risk_weight_correlation, 0.25)
        self.assertEqual(config.risk_weight_exposure, 0.15)
        self.assertEqual(config.risk_budget_vol_min, 0.10)
        self.assertEqual(config.risk_budget_vol_max, 0.45)
        self.assertEqual(config.risk_lookback_days, 120)
        self.assertEqual(config.risk_alert_threshold, 70.0)
        self.assertEqual(config.risk_hard_threshold, 85.0)
        self.assertEqual(config.risk_sizing_corr_floor, 0.30)
        self.assertEqual(config.risk_max_position_pct, 0.25)
        self.assertEqual(config.risk_default_stock_vol, 0.30)
        self.assertEqual(config.risk_default_crypto_vol, 0.60)
        self.assertEqual(config.risk_corr_shrinkage, 0.6)

    def test_load_config_reads_risk_env(self):
        env = {
            "OPENAI_API_KEY": "o",
            "RISK_WEIGHT_CONCENTRATION": "0.4",
            "RISK_LOOKBACK_DAYS": "90",
            "RISK_HARD_THRESHOLD": "80",
            "RISK_MAX_POSITION_PCT": "0.2",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.risk_weight_concentration, 0.4)
        self.assertEqual(config.risk_lookback_days, 90)
        self.assertEqual(config.risk_hard_threshold, 80.0)
        self.assertEqual(config.risk_max_position_pct, 0.2)


if __name__ == "__main__":
    unittest.main()
