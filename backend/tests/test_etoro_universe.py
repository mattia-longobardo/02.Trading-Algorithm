import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import ALL_PROVIDERS, PROVIDER_ETORO, _empty_universe, _normalize_universe_payload


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


if __name__ == "__main__":
    unittest.main()
