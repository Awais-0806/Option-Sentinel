"""
Phase B: pull REAL historical options data from Alpaca using your own
paper credentials, and save it as a CSV that data/market/csv_source.py
can load (provenance=REAL_USER_SUPPLIED_CSV — Claude cannot verify what
happens between Alpaca's servers and your machine, so this is correctly
labeled "user supplied," not "REAL_ALPACA_HISTORICAL," once it round-trips
through a file. If you run this and then load the CSV back in, that's the
honest chain of custody.)

Usage (Windows PowerShell, after `pip install -e .` and setting real
ALPACA_API_KEY/ALPACA_SECRET_KEY in .env):

    python -m scripts.fetch_historical_options --symbol SPY --start 2025-11-01 --end 2026-01-15

Output: data/historical/<SYMBOL>_<start>_<end>.csv

IMPORTANT CAVEATS (read before trusting the output):
- Alpaca's free/Indicative options feed is documented as 15-minute
  delayed and may have limited historical depth/coverage compared to a
  paid OPRA subscription or a dedicated options-history vendor. This
  script does not know your account's exact entitlements — verify the
  row count and date coverage in the printed summary before assuming
  the dataset is complete.
- Open interest is a lagged field per Alpaca's own docs (up to 1 day).
- This script has NOT been executed by Claude against a live account —
  see the Day-3 report for exactly what "not live-verified" means here.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime

from core.config.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch real historical Alpaca option bars to CSV.")
    parser.add_argument("--symbol", required=True, help="Underlying symbol, e.g. SPY")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out", default=None, help="Output CSV path (default: data/historical/<SYMBOL>_<start>_<end>.csv)")
    args = parser.parse_args()

    settings = get_settings()
    if not (settings.alpaca_api_key and settings.alpaca_secret_key):
        print("ERROR: ALPACA_API_KEY/ALPACA_SECRET_KEY not set in .env. This script needs real "
              "paper credentials — it only reads, never trades, but it does need real market-data access.")
        return 1

    try:
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import OptionBarsRequest, StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import AssetStatus
        from alpaca.trading.requests import GetOptionContractsRequest
    except ImportError:
        print("ERROR: alpaca-py is not installed. Run: pip install -e .")
        return 1

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")
    symbol = args.symbol.upper()

    trading = TradingClient(api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key, paper=True)
    stock_data = StockHistoricalDataClient(api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key)
    option_data = OptionHistoricalDataClient(api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key)

    print(f"Fetching underlying {symbol} daily bars {args.start}..{args.end} ...")
    stock_bars_resp = stock_data.get_stock_bars(
        StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start, end=end)
    )
    underlying_close_by_date = {
        bar.timestamp.date().isoformat(): bar.close for bar in stock_bars_resp.data.get(symbol, [])
    }
    print(f"  -> {len(underlying_close_by_date)} underlying daily closes retrieved.")

    print(f"Fetching option contract list for {symbol} (all expirations in range) ...")
    contracts_resp = trading.get_option_contracts(
        GetOptionContractsRequest(
            underlying_symbols=[symbol], status=AssetStatus.ACTIVE,
            expiration_date_gte=start.date(), expiration_date_lte=end.date(),
        )
    )
    contract_list = list(getattr(contracts_resp, "option_contracts", []) or [])
    print(f"  -> {len(contract_list)} contracts found. Fetching daily bars for each (this can be slow/rate-limited) ...")

    rows = []
    for i, meta in enumerate(contract_list):
        try:
            bars_resp = option_data.get_option_bars(
                OptionBarsRequest(symbol_or_symbols=meta.symbol, timeframe=TimeFrame.Day, start=start, end=end)
            )
        except Exception as exc:  # noqa: BLE001 - one bad contract shouldn't kill the whole fetch
            print(f"  WARNING: bars fetch failed for {meta.symbol}: {exc}")
            continue

        for bar in bars_resp.data.get(meta.symbol, []):
            bar_date = bar.timestamp.date().isoformat()
            rows.append({
                "date": bar_date, "underlying": symbol, "expiration": str(meta.expiration_date),
                "strike": meta.strike_price, "right": str(meta.type).upper(),
                "bid": "", "ask": "",  # daily BARS give OHLCV, not bid/ask — see caveat below
                "last": bar.close, "volume": bar.volume,
                "open_interest": getattr(meta, "open_interest", "") or "",
                "underlying_close": underlying_close_by_date.get(bar_date, ""),
            })
        if (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(contract_list)} contracts processed")

    if not rows:
        print("No bar data returned for any contract. Nothing written. This can happen if the "
              "date range predates your account's data entitlement, or the symbol has thin options history.")
        return 1

    out_path = args.out or f"data/historical/{symbol}_{args.start}_{args.end}.csv"
    fieldnames = ["date", "underlying", "expiration", "strike", "right", "bid", "ask", "last",
                  "volume", "open_interest", "underlying_close"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {out_path}")
    print("NOTE: get_option_bars() returns OHLCV bars, not bid/ask quotes — the 'bid'/'ask' "
          "columns above are intentionally empty, not fabricated. data/market/csv_source.py will "
          "load this fine (bid/ask required column check: fill them from 'last' if you accept "
          "using trade price as a proxy, or extend this script to pull get_option_trades()/quotes "
          "for true bid/ask history once you've confirmed your account has that entitlement).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
