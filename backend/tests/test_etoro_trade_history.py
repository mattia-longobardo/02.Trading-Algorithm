import logging
import sys
import unittest
from datetime import date
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig
from clients.etoro_client import EToroClient


def make_config(account_type="demo"):
    return AppConfig(
        openai_api_key="k",
        etoro_api_key="app-key",
        etoro_user_key="user-key",
        etoro_account_type=account_type,
    )


def make_response(status_code=200, json_body=None):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = "" if json_body is None else str(json_body)
    return resp


def make_client(account_type="demo"):
    session = Mock()
    client = EToroClient(
        make_config(account_type),
        logging.getLogger("test"),
        session=session,
        rate_limiter=Mock(),
    )
    return client, session


RAW_TRADE = {
    "netProfit": 537.80,
    "closeRate": 66393.87,
    "closeTimestamp": "2026-06-15T21:46:03.84Z",
    "positionId": 3535850729,
    "instrumentId": 100000,
    "isBuy": True,
    "openRate": 63444.08,
    "openTimestamp": "2026-06-08T10:00:00Z",
    "investment": 11567.06,
    "fees": 0.0,
    "units": 0.182319,
}


class TradeHistoryTests(unittest.TestCase):
    def test_normalizes_history_fields(self):
        client, session = make_client()
        session.request.side_effect = [make_response(200, [RAW_TRADE])]
        rows = client.list_trade_history(date(2026, 6, 1))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["position_id"], "3535850729")
        self.assertEqual(r["instrument_id"], 100000)
        self.assertAlmostEqual(r["net_profit"], 537.80)
        self.assertAlmostEqual(r["close_rate"], 66393.87)
        self.assertAlmostEqual(r["open_rate"], 63444.08)
        self.assertAlmostEqual(r["units"], 0.182319)
        self.assertEqual(r["close_timestamp"], "2026-06-15T21:46:03.84Z")
        self.assertTrue(r["is_buy"])

    def test_sends_min_date_and_demo_path(self):
        client, session = make_client("demo")
        session.request.side_effect = [make_response(200, [])]
        client.list_trade_history(date(2026, 6, 1))
        args, kwargs = session.request.call_args
        url = args[1] if len(args) > 1 else kwargs.get("url", "")
        self.assertIn("/api/v1/trading/info/trade/demo/history", url)
        self.assertEqual(kwargs["params"]["minDate"], "2026-06-01")

    def test_real_account_uses_non_demo_path(self):
        client, session = make_client("real")
        session.request.side_effect = [make_response(200, [])]
        client.list_trade_history(date(2026, 6, 1))
        args, kwargs = session.request.call_args
        url = args[1] if len(args) > 1 else kwargs.get("url", "")
        self.assertIn("/api/v1/trading/info/trade/history", url)
        self.assertNotIn("demo", url)

    def test_paginates_until_short_page(self):
        client, session = make_client()
        full_page = [dict(RAW_TRADE, positionId=i) for i in range(2)]
        session.request.side_effect = [
            make_response(200, full_page),  # page 1 (full -> fetch more)
            make_response(200, [dict(RAW_TRADE, positionId=99)]),  # page 2 (short -> stop)
        ]
        rows = client.list_trade_history(date(2026, 6, 1), page_size=2)
        self.assertEqual(len(rows), 3)
        self.assertEqual(session.request.call_count, 2)
        self.assertEqual(session.request.call_args_list[1].kwargs["params"]["page"], 2)

    def test_stops_on_empty_first_page(self):
        client, session = make_client()
        session.request.side_effect = [make_response(200, [])]
        rows = client.list_trade_history(date(2026, 6, 1))
        self.assertEqual(rows, [])
        self.assertEqual(session.request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
