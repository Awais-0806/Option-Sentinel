"""
Phase B/Day-4 Phase 2: pull REAL historical options data from Alpaca using
your own paper credentials, and save it as a CSV that
data/market/csv_source.py can load (provenance=REAL_USER_SUPPLIED_CSV).

Usage (Windows PowerShell, after `pip install -e .` and setting real
ALPACA_API_KEY/ALPACA_SECRET_KEY in .env):

    python -m scripts.fetch_historical_options --symbol SPY --start 2025-11-01 --end 2026-01-15

Start with a SMALL sample (a few weeks) before attempting a large range —
this script makes one API call per contract for bars, which can be slow
and is subject to Alpaca's rate limits.

Output:
    data/historical/<SYMBOL>_<start>_<end>.csv           (normalized, what csv_source.py loads)
    data/historical/<SYMBOL>_<start>_<end>.raw.jsonl      (raw API responses, one JSON object per line —
                                                            preserves provenance per requirement #3)
    data/historical/<SYMBOL>_<start>_<end>.meta.json      (retrieval timestamp, SDK version, request
                                                            params, record counts — requirement #3/#4)

RETRY BEHAVIOR: transient failures (timeouts, 429/5xx-style exceptions)
are retried up to 3 times with exponential backoff (1s, 2s, 4s) per
contract. A contract that still fails after retries is skipped and
logged — it does NOT abort the whole run, and it is NOT silently
counted as "zero volume" or any other invented value.

IMPORTANT CAVEATS (read before trusting the output — see
docs/ALPACA_DATA_CAPABILITY_MATRIX.md for the full, sourced version):
- Alpaca's get_option_bars() returns OHLCV trade bars — it does NOT
  carry bid/ask, IV, Greeks, or open-interest history. The 'bid'/'ask'
  columns in the output CSV will be empty for this reason, not by bug.
- Open interest (when present, from contract metadata) is lagged up to
  1 day per Alpaca's own docs.
- This script has NOT been executed by Claude against a live account.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone

from core.config.settings import get_settings

MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.0


def _with_retries(fn, *, description: str, log):
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - genuinely need to catch anything transient here
            last_exc = exc
            log(f"  WARNING: {description} failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    log(f"  GIVING UP on {description} after {MAX_RETRIES} attempts: {last_exc}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch real historical Alpaca option bars to CSV.")
    parser.add_argument("--symbol", required=True, help="Underlying symbol, e.g. SPY")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--timeframe", default="1Day", choices=["1Day"], help="Bar timeframe (only daily supported currently)")
    parser.add_argument("--out", default=None, help="Output CSV path (default: data/historical/<SYMBOL>_<start>_<end>.csv)")
    parser.add_argument("--max-contracts", type=int, default=None, help="Cap the number of contracts fetched (for a quick small-sample test)")
    args = parser.parse_args()

    def log(msg: str):
        print(msg)

    settings = get_settings()
    if not (settings.alpaca_api_key and settings.alpaca_secret_key):
        log("ERROR: ALPACA_API_KEY/ALPACA_SECRET_KEY not set in .env. This script needs real "
            "paper credentials — it only reads, never trades, but it does need real market-data access.")
        return 1

    try:
        import alpaca
        alpaca_version = getattr(alpaca, "__version__", "unknown")
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import OptionBarsRequest, StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import AssetStatus
        from alpaca.trading.requests import GetOptionContractsRequest
    except ImportError as exc:
        log(f"ERROR: alpaca-py is not installed or import failed: {exc}. Run: pip install -e .")
        return 1

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")
    symbol = args.symbol.upper()
    retrieved_at = datetime.now(timezone.utc).isoformat()

    trading = TradingClient(api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key, paper=True)
    stock_data = StockHistoricalDataClient(api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key)
    option_data = OptionHistoricalDataClient(api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key)

    log(f"alpaca-py version: {alpaca_version}")
    log(f"Fetching underlying {symbol} daily bars {args.start}..{args.end} ...")
    stock_bars_resp = _with_retries(
        lambda: stock_data.get_stock_bars(StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start, end=end)),
        description="underlying stock bars fetch", log=log,
    )
    if stock_bars_resp is None:
        log("ERROR: could not fetch underlying bars after retries. Aborting.")
        return 1
    underlying_close_by_date = {bar.timestamp.date().isoformat(): bar.close for bar in stock_bars_resp.data.get(symbol, [])}
    log(f"  -> {len(underlying_close_by_date)} underlying daily closes retrieved.")

    log(f"Fetching option contract list for {symbol} (all expirations in range) ...")
    contracts_resp = _with_retries(
        lambda: trading.get_option_contracts(GetOptionContractsRequest(
            underlying_symbols=[symbol], status=AssetStatus.ACTIVE,
            expiration_date_gte=start.date(), expiration_date_lte=end.date(),
        )),
        description="option contract list fetch", log=log,
    )
    if contracts_resp is None:
        log("ERROR: could not fetch contract list after retries. Aborting.")
        return 1
    contract_list = list(getattr(contracts_resp, "option_contracts", []) or [])
    if args.max_contracts:
        contract_list = contract_list[: args.max_contracts]
    log(f"  -> {len(contract_list)} contracts to fetch bars for (this can be slow/rate-limited) ...")

    rows = []
    raw_records = []
    failed_contracts = []
    for i, meta in enumerate(contract_list):
        bars_resp = _with_retries(
            lambda meta=meta: option_data.get_option_bars(
                OptionBarsRequest(symbol_or_symbols=meta.symbol, timeframe=TimeFrame.Day, start=start, end=end)
            ),
            description=f"bars fetch for {meta.symbol}", log=log,
        )
        if bars_resp is None:
            failed_contracts.append(meta.symbol)
            continue

        contract_bars = bars_resp.data.get(meta.symbol, [])
        raw_records.append({
            "contract_symbol": meta.symbol, "strike": str(meta.strike_price),
            "expiration": str(meta.expiration_date), "type": str(meta.type),
            "open_interest": getattr(meta, "open_interest", None),
            "bar_count": len(contract_bars),
            "bars": [{"t": b.timestamp.isoformat(), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume} for b in contract_bars],
        })

        for bar in contract_bars:
            bar_date = bar.timestamp.date().isoformat()
            rows.append({
                "date": bar_date, "underlying": symbol, "expiration": str(meta.expiration_date),
                "strike": meta.strike_price, "right": str(meta.type).upper(),
                "bid": "", "ask": "",  # get_option_bars gives OHLCV, not bid/ask — see module docstring
                "last": bar.close, "volume": bar.volume,
                "open_interest": getattr(meta, "open_interest", "") or "",
                "underlying_close": underlying_close_by_date.get(bar_date, ""),
            })
        if (i + 1) % 25 == 0:
            log(f"  ... {i + 1}/{len(contract_list)} contracts processed")

    if not rows:
        log("No bar data returned for any contract. Nothing written. This can happen if the "
            "date range predates your account's data entitlement, or the symbol has thin options history.")
        return 1

    base = args.out.rsplit(".", 1)[0] if args.out else f"data/historical/{symbol}_{args.start}_{args.end}"
    csv_path = f"{base}.csv"
    raw_path = f"{base}.raw.jsonl"
    meta_path = f"{base}.meta.json"

    fieldnames = ["date", "underlying", "expiration", "strike", "right", "bid", "ask", "last",
                  "volume", "open_interest", "underlying_close"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with open(raw_path, "w", encoding="utf-8") as f:
        for record in raw_records:
            f.write(json.dumps(record, default=str) + "\n")

    metadata = {
        "retrieved_at": retrieved_at,
        "alpaca_py_version": alpaca_version,
        "request_parameters": {"symbol": symbol, "start": args.start, "end": args.end, "timeframe": args.timeframe},
        "contracts_requested": len(contract_list),
        "contracts_succeeded": len(contract_list) - len(failed_contracts),
        "contracts_failed": failed_contracts,
        "bar_row_count": len(rows),
        "underlying_bar_count": len(underlying_close_by_date),
        "csv_path": csv_path, "raw_path": raw_path,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str)

    log(f"\nWrote {len(rows)} rows to {csv_path}")
    log(f"Raw responses preserved at {raw_path}")
    log(f"Retrieval metadata at {meta_path}")
    if failed_contracts:
        log(f"WARNING: {len(failed_contracts)} contracts failed after retries and were skipped: {failed_contracts[:10]}{'...' if len(failed_contracts) > 10 else ''}")
    log("\nNOTE: 'bid'/'ask' columns are intentionally empty — get_option_bars() does not carry "
        "quotes. Run this through data/market/csv_source.py and backtest/data_capability.py to see "
        "exactly what this means for backtest evaluability (very likely NOT_EVALUATABLE for "
        "spread-cost-aware strategy backtests — see docs/ALPACA_DATA_CAPABILITY_MATRIX.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
