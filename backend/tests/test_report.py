import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

alpaca_client_stub = ModuleType("clients.alpaca_client")
alpaca_client_stub.AlpacaClient = object
sys.modules.setdefault("clients.alpaca_client", alpaca_client_stub)

gpt_client_stub = ModuleType("clients.gpt_client")
gpt_client_stub.GPTClient = object
gpt_client_stub.get_default_prompts = lambda: {}
sys.modules.setdefault("clients.gpt_client", gpt_client_stub)

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig
from services.report import ReportGenerator


class ReportGeneratorTests(unittest.TestCase):
    def test_generate_weekly_report_writes_files_to_configured_report_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir) / "reports"
            trade_manager = Mock()
            trade_manager.weekly_summary.return_value = {
                "open_trades": [],
                "pending_trades": [],
                "closed_trades": [],
                "cancelled_trades": [],
                "pnl_total": 0.0,
                "pnl_by_category": {},
                "win_rate": 0.0,
                "best_trade": None,
                "worst_trade": None,
                "most_traded_symbols": [],
            }
            config = AppConfig(
                openai_api_key="test-openai-key",
                
                
                
                report_dir=str(report_dir),
            )

            generator = ReportGenerator(config, logging.getLogger("test"), trade_manager)
            report = generator.generate_weekly_report()

            self.assertEqual(report["pnl_total"], 0.0)
            generated_files = sorted(path.name for path in report_dir.iterdir())
            self.assertEqual(len(generated_files), 2)
            self.assertTrue(any(name.endswith(".json") for name in generated_files))
            pdf_files = [name for name in generated_files if name.endswith(".pdf")]
            self.assertEqual(len(pdf_files), 1)
            pdf_bytes = (report_dir / pdf_files[0]).read_bytes()
            self.assertTrue(pdf_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
