"""
Loads a user-supplied CSV of real historical options data into the shared
HistoricalDataset schema, tagged DataProvenance.REAL_USER_SUPPLIED_CSV.

Required CSV columns (header row required, any column order):
    date            YYYY-MM-DD  (the as-of/quote date)
    underlying      e.g. SPY
    expiration      YYYY-MM-DD
    strike          numeric
    right           CALL or PUT
    bid             numeric
    ask             numeric
    underlying_close  numeric — the underlying's close on `date`

Optional columns (used if present, left as None if absent — never
fabricated):
    last, volume, open_interest, implied_volatility, delta, gamma, theta, vega

If optional columns are missing, this loader records exactly which ones
in the returned dataset's metadata under "missing_optional_fields" —
per Phase B: "If fields are missing, explicitly document them. Do NOT
fabricate missing fields."
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

from backtest.data_schema import DataProvenance, HistoricalDataset, HistoricalDay
from core.models.options import OptionContract, OptionRight

REQUIRED_COLUMNS = {"date", "underlying", "expiration", "strike", "right", "bid", "ask", "underlying_close"}
OPTIONAL_COLUMNS = {"last", "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"}


class CsvSchemaError(ValueError):
    pass


def _parse_date(value: str) -> date_cls:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def _opt_float(row: dict, key: str) -> float | None:
    raw = row.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_csv_dataset(path: str | Path, underlying: str | None = None) -> HistoricalDataset:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise CsvSchemaError(f"{path} has no header row")
        columns = set(reader.fieldnames)
        missing_required = REQUIRED_COLUMNS - columns
        if missing_required:
            raise CsvSchemaError(
                f"{path} is missing required columns: {sorted(missing_required)}. "
                f"Required: {sorted(REQUIRED_COLUMNS)}"
            )
        missing_optional = sorted(OPTIONAL_COLUMNS - columns)

        by_date: dict[date_cls, list[OptionContract]] = defaultdict(list)
        underlying_close_by_date: dict[date_cls, float] = {}
        row_count = 0
        detected_underlying: str | None = None
        bid_ask_synthesized_count = 0

        for row in reader:
            row_count += 1
            as_of = _parse_date(row["date"])
            row_underlying = row["underlying"].strip().upper()
            detected_underlying = detected_underlying or row_underlying
            expiration = _parse_date(row["expiration"])
            right = OptionRight.CALL if row["right"].strip().upper().startswith("C") else OptionRight.PUT
            bid_raw = _opt_float(row, "bid")
            ask_raw = _opt_float(row, "ask")
            last_raw = _opt_float(row, "last")
            if bid_raw is None and ask_raw is None and last_raw is not None:
                # Alpaca's get_option_bars() gives OHLCV (trade-derived), not bid/ask quotes —
                # a true historical bid/ask series may not be available at all (see
                # scripts/fetch_historical_options.py). Disclosed approximation, not fabrication:
                # both bid and ask are set to the last trade price, i.e. zero synthetic spread.
                bid = ask = last_raw
                bid_ask_synthesized_count += 1
            elif bid_raw is not None and ask_raw is not None:
                bid, ask = bid_raw, ask_raw
            else:
                raise CsvSchemaError(
                    f"{path} row {row_count}: bid/ask are partially present and cannot be reconciled "
                    "(need both bid+ask, or neither with a 'last' column to fall back on)"
                )
            underlying_close_by_date[as_of] = float(row["underlying_close"])

            contract = OptionContract(
                symbol=row.get("symbol", "").strip() or f"{row_underlying}{expiration.isoformat()}{right.value[0]}{row['strike']}",
                underlying=row_underlying,
                expiration=expiration,
                strike=float(row["strike"]),
                right=right,
                bid=bid,
                ask=ask,
                last=_opt_float(row, "last"),
                volume=int(_opt_float(row, "volume") or 0),
                open_interest=int(_opt_float(row, "open_interest") or 0),
                implied_volatility=_opt_float(row, "implied_volatility"),
                delta=_opt_float(row, "delta"),
                gamma=_opt_float(row, "gamma"),
                theta=_opt_float(row, "theta"),
                vega=_opt_float(row, "vega"),
            )
            by_date[as_of].append(contract)

    if row_count == 0:
        raise CsvSchemaError(f"{path} has a header but zero data rows")

    resolved_underlying = underlying or detected_underlying
    days = tuple(
        HistoricalDay(
            as_of_date=d, underlying=resolved_underlying,
            underlying_close=underlying_close_by_date[d], contracts=tuple(contracts),
        )
        for d, contracts in sorted(by_date.items())
    )

    metadata = {
        "source_path": str(path),
        "row_count": row_count,
        "date_range": [days[0].as_of_date.isoformat(), days[-1].as_of_date.isoformat()],
        "missing_optional_fields": missing_optional,
        "bid_ask_synthesized_from_last_count": bid_ask_synthesized_count,
        "bid_ask_synthesized_note": (
            "Rows counted here had no real bid/ask; bid=ask=last trade price was used as a "
            "disclosed zero-spread approximation, not a real quoted spread."
            if bid_ask_synthesized_count > 0 else None
        ),
    }
    return HistoricalDataset(
        underlying=resolved_underlying, provenance=DataProvenance.REAL_USER_SUPPLIED_CSV, days=days, metadata=metadata
    )
