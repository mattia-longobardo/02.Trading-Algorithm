import os
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig, PROVIDER_ETORO, load_config


class EtoroConfigTests(unittest.TestCase):
    def test_provider_constant(self):
        self.assertEqual(PROVIDER_ETORO, "etoro")

    def test_demo_property_defaults_true(self):
        config = AppConfig(
            openai_api_key="k",
            alpaca_api_key="",
            alpaca_secret_key="",
            alpaca_base_url="https://paper-api.alpaca.markets",
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
            alpaca_api_key="",
            alpaca_secret_key="",
            alpaca_base_url="x",
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


if __name__ == "__main__":
    unittest.main()
