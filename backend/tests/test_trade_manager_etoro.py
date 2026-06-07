import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

for name, attr in (("clients.alpaca_client", "AlpacaClient"), ("clients.gpt_client", "GPTClient")):
    stub = ModuleType(name)
    setattr(stub, attr, object)
    if name == "clients.gpt_client":
        stub.get_default_prompts = lambda: {}
    sys.modules.setdefault(name, stub)
dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases
from core.utils import AppConfig, PROVIDER_ETORO
from services.trade_manager import TradeManager


def make_config(trades_db, market_db):
    return AppConfig(
        openai_api_key="k", 
        etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo",
        db_trades=trades_db, db_market_data=market_db,
        crypto_entry_max_chase_bps=40, crypto_pending_cancel_minutes=12,
    )


class EtoroLifecycleBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        initialize_databases(self.market_db, self.trades_db)
        self.config = make_config(self.trades_db, self.market_db)
        self.broker = Mock()
        self.broker.instrument_id_for_symbol.return_value = 101
        self.broker.get_open_position.return_value = None
        self.broker.get_available_cash.return_value = 1000.0
        self.broker.is_market_open.return_value = True
        self.data_manager = Mock()
        self.gpt = Mock()
        self.manager = TradeManager(
            self.config, logging.getLogger("t"), {PROVIDER_ETORO: self.broker}, self.data_manager, self.gpt
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self, status=None):
        conn = sqlite3.connect(self.trades_db)
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM trades"
        if status:
            q += f" WHERE status = '{status}'"
        rows = [dict(r) for r in conn.execute(q)]
        conn.close()
        return rows

    def _signal(self, **over):
        s = {"action": "OPEN", "symbol": "AAPL", "entry_price": 100.0, "take_profit": 120.0,
             "stop_loss": 90.0, "trailing_take_profit_distance": None,
             "trailing_take_profit_activation_pct": None, "trailing_stop_distance": None,
             "trade_score": 80.0, "confidence": 0.9, "reasoning": "x"}
        s.update(over)
        return s


class EtoroEntryTests(EtoroLifecycleBase):
    def test_open_stores_pending_without_broker_order(self):
        ok = self.manager._open_trade_from_signal("STOCK", "AAPL", self._signal(), provider=PROVIDER_ETORO)
        self.assertTrue(ok)
        self.broker.open_market_position.assert_not_called()
        rows = self._rows("PENDING")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["instrument_id"], 101)
        self.assertEqual(rows[0]["target_entry_price"], 100.0)
        self.assertEqual(rows[0]["provider"], "etoro")

    def test_open_skips_when_instrument_unknown(self):
        self.broker.instrument_id_for_symbol.return_value = None
        ok = self.manager._open_trade_from_signal("STOCK", "NOPE", self._signal(symbol="NOPE"), provider=PROVIDER_ETORO)
        self.assertFalse(ok)
        self.assertEqual(self._rows(), [])

    def test_open_skips_when_stock_market_closed(self):
        self.broker.is_market_open.return_value = False
        ok = self.manager._open_trade_from_signal("STOCK", "AAPL", self._signal(), provider=PROVIDER_ETORO)
        self.assertFalse(ok)
        self.assertEqual(self._rows(), [])  # no PENDING created → no order → no churn

    def test_open_proceeds_for_crypto_without_market_check(self):
        # Even if the market-open check would say "closed", crypto trades 24/7
        # and must not consult it.
        self.broker.is_market_open.return_value = False
        ok = self.manager._open_trade_from_signal("CRYPTO", "BTC", self._signal(symbol="BTC"), provider=PROVIDER_ETORO)
        self.assertTrue(ok)
        self.broker.is_market_open.assert_not_called()
        self.assertEqual(len(self._rows("PENDING")), 1)


class EtoroPendingTests(EtoroLifecycleBase):
    def _pending(self, target=100.0):
        self.manager._save_new_trade("STOCK", "AAPL", self._signal(entry_price=target), 101, 200.0, provider=PROVIDER_ETORO)
        return self._rows("PENDING")[0]

    def test_fill_when_price_touches_target(self):
        trade = self._pending(target=100.0)
        self.broker.get_latest_quote.return_value = {"ask_price": 100.0, "bid_price": 99.9}
        self.broker.open_market_position.return_value = {
            "order_id": "o1", "reference_id": "r1", "request_id": "req1", "position_id": "p1", "raw": {}}
        position = {
            "position_id": "p1", "instrument_id": 101, "units": 2.0, "open_rate": 100.0,
            "amount": 200.0, "is_buy": True}
        # Tick 1: price touches target → open_market_position fires → order submitted (PENDING with order_id).
        # get_open_position returns None on the pre-fill check inside sync_pending_trade.
        self.broker.get_open_position.return_value = None
        self.broker.get_latest_price.return_value = 101.0
        self.manager.sync_pending_trade(trade)
        self.broker.open_market_position.assert_called_once()
        kwargs = self.broker.open_market_position.call_args.kwargs
        self.assertEqual(kwargs["amount_usd"], 200.0)
        self.assertEqual(kwargs["stop_loss_rate"], 90.0)
        self.assertEqual(kwargs["take_profit_rate"], 120.0)
        self.assertEqual(kwargs["leverage"], 1)
        # After tick 1 the trade is still PENDING but now carries order_id.
        self.assertEqual(len(self._rows("PENDING")), 1)
        self.assertEqual(self._rows("PENDING")[0]["order_id"], "o1")
        # Tick 2: _resolve_submitted_order sees executed=True → activates to OPEN.
        self.broker.get_order_status.return_value = {
            "executed": True, "rejected": False, "canceled": False, "waiting": False,
            "position_id": "p1", "error_message": None}
        self.broker.get_open_position.return_value = position
        trade2 = self._rows("PENDING")[0]
        self.manager.sync_pending_trade(trade2)
        row = self._rows("OPEN")[0]
        self.assertEqual(row["position_id"], "p1")
        self.assertEqual(row["quantity"], 2.0)
        self.assertEqual(row["entry_price"], 100.0)
        self.assertEqual(row["position_confirmed"], 1)

    def test_no_fill_when_price_above_chase(self):
        trade = self._pending(target=100.0)
        self.broker.get_latest_quote.return_value = {"ask_price": 105.0, "bid_price": 104.9}
        self.manager.sync_pending_trade(trade)
        self.broker.open_market_position.assert_not_called()
        self.assertEqual(len(self._rows("PENDING")), 1)

    def test_timeout_cancels_pending(self):
        trade = self._pending(target=100.0)
        conn = sqlite3.connect(self.trades_db)
        conn.execute("UPDATE trades SET created_at = datetime('now','-1 day') WHERE id = ?", (trade["id"],))
        conn.commit(); conn.close()
        trade = self._rows("PENDING")[0]
        self.broker.get_latest_quote.return_value = {"ask_price": 105.0, "bid_price": 104.9}
        self.manager.sync_pending_trade(trade)
        self.broker.open_market_position.assert_not_called()
        self.assertEqual(self._rows("CANCELLED")[0]["close_reason"], "ENTRY_TIMEOUT")


class EtoroExitTests(EtoroLifecycleBase):
    def _open_trade(self, **over):
        self.manager._save_new_trade("STOCK", "AAPL", self._signal(**over), 101, 200.0, provider=PROVIDER_ETORO)
        t = self._rows("PENDING")[0]
        pos = {"position_id": "p1", "instrument_id": 101, "units": 2.0, "open_rate": 100.0, "amount": 200.0, "is_buy": True}
        self.broker.get_latest_price.return_value = 100.0
        self.manager._activate_trade_from_position(t, pos, {"position_id": "p1", "reference_id": "r1"})
        return self._rows("OPEN")[0]

    def test_take_profit_triggers_close_by_position_id(self):
        trade = self._open_trade(take_profit=120.0)
        self.broker.get_open_position.return_value = {
            "position_id": "p1", "instrument_id": 101, "units": 2.0, "open_rate": 100.0, "amount": 200.0, "is_buy": True}
        self.broker.get_latest_price.return_value = 125.0

        def _after_close(*a, **k):
            self.broker.get_open_position.return_value = None
            return {"order_id": "c1", "raw": {}}
        self.broker.close_position_market.side_effect = _after_close
        self.manager.sync_open_trade(trade)
        self.broker.close_position_market.assert_called_once_with("p1", instrument_id=101)
        closed = self._rows("CLOSED")[0]
        self.assertEqual(closed["close_reason"], "TAKE_PROFIT")

    def test_position_vanished_closes_trade(self):
        trade = self._open_trade()
        self.broker.get_open_position.return_value = None
        self.manager.sync_open_trade(trade)
        self.assertEqual(len(self._rows("CLOSED")), 1)


if __name__ == "__main__":
    unittest.main()
