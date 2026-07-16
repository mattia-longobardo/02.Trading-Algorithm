import logging
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.app_db import app_cursor, initialize_app_database
from core.utils import AppConfig, isoformat_utc, utc_now
from services.benchmark import BenchmarkService


def _day(offset_days: int) -> str:
    dt = (utc_now() - timedelta(days=offset_days)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    return isoformat_utc(dt) or ""


def _day_bucket(offset_days: int) -> str:
    dt = (utc_now() - timedelta(days=offset_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return dt.strftime("%Y-%m-%dT00:00:00+00:00")


class BenchmarkServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_db = str(Path(self.tmp.name) / "app.sqlite")
        initialize_app_database(self.app_db)
        # Valuta account == valuta display: nessuna conversione FX nei test.
        self.config = AppConfig(
            openai_api_key="k",
            etoro_api_key="a",
            etoro_user_key="b",
            etoro_account_type="demo",
            db_app=self.app_db,
            currency="USD",
            account_currency="USD",
        )
        self.service = BenchmarkService(self.config, logging.getLogger("t"))

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_equity(self, rows):
        with app_cursor(self.app_db) as cursor:
            for recorded_at, equity in rows:
                cursor.execute(
                    "INSERT INTO account_equity_snapshots (recorded_at, equity, currency, provider) VALUES (?, ?, ?, 'etoro')",
                    (recorded_at, equity, "USD"),
                )

    def _broker(self, candles):
        broker = Mock()
        broker.instrument_id_for_symbol.return_value = 100000
        broker.get_candles_by_instrument.return_value = candles
        return broker

    def test_normalizes_both_series_from_common_start(self):
        self._seed_equity([(_day(2), 1000.0), (_day(1), 1050.0), (_day(0), 1100.0)])
        broker = self._broker(
            [
                {"timestamp": _day(2), "close": 5000.0},
                {"timestamp": _day(1), "close": 5100.0},
                {"timestamp": _day(0), "close": 4950.0},
            ]
        )
        out = self.service.comparison(broker, from_dt=None, to_dt=None)

        self.assertEqual(len(out["points"]), 3)
        first, _, last = out["points"]
        self.assertEqual(first, {"t": _day_bucket(2), "portfolio_pct": 0.0, "benchmark_pct": 0.0})
        self.assertEqual(last["portfolio_pct"], 10.0)
        self.assertEqual(last["benchmark_pct"], -1.0)
        self.assertEqual(out["summary"]["portfolio_pct"], 10.0)
        self.assertEqual(out["summary"]["benchmark_pct"], -1.0)
        self.assertEqual(out["summary"]["alpha_pct"], 11.0)
        self.assertEqual(out["summary"]["currency"], "USD")
        self.assertIsNone(out["benchmark"]["error"])

    def test_clips_benchmark_to_portfolio_first_snapshot(self):
        # Conto partito 1 giorno fa, indice disponibile da 5: il rendimento
        # dell'indice deve ripartire da 0 alla data del primo snapshot.
        self._seed_equity([(_day(1), 1000.0), (_day(0), 990.0)])
        broker = self._broker(
            [
                {"timestamp": _day(5), "close": 4000.0},
                {"timestamp": _day(1), "close": 5000.0},
                {"timestamp": _day(0), "close": 5250.0},
            ]
        )
        out = self.service.comparison(broker, from_dt=None, to_dt=None)

        self.assertEqual([p["t"] for p in out["points"]], [_day_bucket(1), _day_bucket(0)])
        self.assertEqual(out["points"][0]["benchmark_pct"], 0.0)
        self.assertEqual(out["points"][1]["benchmark_pct"], 5.0)
        self.assertEqual(out["summary"]["portfolio_pct"], -1.0)
        self.assertEqual(out["summary"]["alpha_pct"], -6.0)

    def test_anchors_benchmark_to_last_close_before_weekend_start(self):
        # Bot partito di sabato (nessuna candela quel giorno): l'indice deve
        # partire da 0 alla stessa data usando la chiusura di venerdì come
        # base, senza lasciare buchi iniziali nel grafico.
        self._seed_equity([(_day(2), 1000.0), (_day(1), 1010.0), (_day(0), 1020.0)])
        broker = self._broker(
            [
                {"timestamp": _day(4), "close": 7350.0},  # "venerdì"
                {"timestamp": _day(1), "close": 7433.0},  # "lunedì"
                {"timestamp": _day(0), "close": 7500.0},
            ]
        )
        out = self.service.comparison(broker, from_dt=None, to_dt=None)

        self.assertEqual([p["t"] for p in out["points"]],
                         [_day_bucket(2), _day_bucket(1), _day_bucket(0)])
        first = out["points"][0]
        self.assertEqual(first["benchmark_pct"], 0.0)  # anchored to Friday close
        self.assertEqual(out["points"][1]["benchmark_pct"], 1.13)  # 7350 → 7433
        self.assertEqual(out["points"][2]["benchmark_pct"], 2.04)  # 7350 → 7500
        self.assertEqual(out["benchmark"]["points_count"], 3)

    def test_window_start_keeps_pre_window_anchor(self):
        # Finestra esplicita che parte in un giorno senza candela: la candela
        # precedente fa da base ma la serie non deve estendersi prima della
        # finestra selezionata.
        self._seed_equity([(_day(1), 1000.0), (_day(0), 1100.0)])
        broker = self._broker(
            [
                {"timestamp": _day(3), "close": 100.0},
                {"timestamp": _day(0), "close": 110.0},
            ]
        )
        from_dt = (utc_now() - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        out = self.service.comparison(broker, from_dt=from_dt, to_dt=None)

        self.assertEqual([p["t"] for p in out["points"]], [_day_bucket(1), _day_bucket(0)])
        self.assertEqual(out["points"][0]["benchmark_pct"], 0.0)
        self.assertEqual(out["points"][1]["benchmark_pct"], 10.0)

    def test_forward_fills_benchmark_gaps(self):
        # Weekend: nessuna candela per il giorno centrale — la linea benchmark
        # mantiene l'ultimo valore noto invece di bucare il grafico.
        self._seed_equity([(_day(2), 1000.0), (_day(1), 1010.0), (_day(0), 1020.0)])
        broker = self._broker(
            [
                {"timestamp": _day(2), "close": 5000.0},
                {"timestamp": _day(0), "close": 5500.0},
            ]
        )
        out = self.service.comparison(broker, from_dt=None, to_dt=None)

        middle = out["points"][1]
        self.assertEqual(middle["t"], _day_bucket(1))
        self.assertEqual(middle["portfolio_pct"], 1.0)
        self.assertEqual(middle["benchmark_pct"], 0.0)  # carried forward

    def test_no_broker_returns_portfolio_only(self):
        self._seed_equity([(_day(1), 1000.0), (_day(0), 1100.0)])
        out = self.service.comparison(None, from_dt=None, to_dt=None)

        self.assertEqual(out["benchmark"]["error"], "no_broker_configured")
        self.assertEqual(out["benchmark"]["points_count"], 0)
        self.assertEqual(len(out["points"]), 2)
        self.assertIsNone(out["points"][-1]["benchmark_pct"])
        self.assertEqual(out["summary"]["portfolio_pct"], 10.0)
        self.assertIsNone(out["summary"]["alpha_pct"])

    def test_broker_error_is_graceful(self):
        self._seed_equity([(_day(1), 1000.0), (_day(0), 1100.0)])
        broker = Mock()
        broker.instrument_id_for_symbol.return_value = None
        out = self.service.comparison(broker, from_dt=None, to_dt=None)

        self.assertIsNotNone(out["benchmark"]["error"])
        self.assertEqual(len(out["points"]), 2)
        self.assertEqual(out["summary"]["portfolio_pct"], 10.0)

    def test_empty_database_returns_empty_payload(self):
        broker = self._broker([])
        out = self.service.comparison(broker, from_dt=None, to_dt=None)

        self.assertEqual(out["points"], [])
        self.assertIsNone(out["summary"])

    def test_candles_are_cached_between_calls(self):
        self._seed_equity([(_day(1), 1000.0), (_day(0), 1100.0)])
        broker = self._broker([{"timestamp": _day(0), "close": 5000.0}])
        self.service.comparison(broker, from_dt=None, to_dt=None)
        self.service.comparison(broker, from_dt=None, to_dt=None)

        self.assertEqual(broker.get_candles_by_instrument.call_count, 1)


if __name__ == "__main__":
    unittest.main()
