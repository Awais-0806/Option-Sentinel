from __future__ import annotations

import json
import sys

from core.config.settings import get_settings
from scripts.run_backtest import main


def test_cli_report_includes_buy_and_hold_and_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "historical").mkdir(parents=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_backtest",
            "--symbol",
            "SPY",
            "--start",
            "2025-01-01",
            "--end",
            "2025-04-15",
            "--data",
            "synthetic",
            "--starting-equity",
            "250000",
        ],
    )
    get_settings.cache_clear()

    try:
        assert main() == 0
        report_path = tmp_path / "data" / "historical" / "backtest_report_SPY_2025-01-01_2025-04-15_synthetic.json"
        first_output = report_path.read_bytes()
        report = json.loads(first_output)

        assert "generated_at" not in report
        assert report["buy_and_hold"]["starting_equity"] == 250000.0
        assert report["buy_and_hold"]["start_date"]
        assert report["buy_and_hold"]["end_date"]

        assert main() == 0
        assert report_path.read_bytes() == first_output
    finally:
        get_settings.cache_clear()
