# Alpaca Options Data — Capability Matrix

**Version caveat, stated once, applies to the whole document**: this matrix is built from Alpaca's current public API reference pages and official example notebooks (researched via web search — see citations at the bottom), NOT from an installed copy of `alpaca-py`. I do not have network access to run `pip show alpaca-py` or exercise the SDK in this sandbox, so I **cannot confirm this matches version `0.44.0` specifically** — Alpaca's docs site does not appear to version-pin its content by SDK release. **You must verify this table against your own installed version** (`pip show alpaca-py`) before trusting it for anything beyond "what to try first."

| Field | Live snapshot (`get_option_chain` / `get_option_snapshot`) | Historical bars (`get_option_bars`) | Contract metadata (`get_option_contracts`) | Required by our strategies | Available for backtesting? |
|---|---|---|---|---|---|
| underlying symbol | ✅ | ✅ | ✅ | ✅ | ✅ |
| timestamp | ✅ (quote/trade timestamp) | ✅ (bar timestamp) | — | ✅ | ✅ (bar-level, daily) |
| strike | — (keyed by contract symbol, not a field) | — (keyed by contract symbol) | ✅ | ✅ | ✅ (from contract metadata) |
| expiration | — (via contract symbol) | — (via contract symbol) | ✅ | ✅ | ✅ (from contract metadata) |
| call/put | — (via contract symbol) | — (via contract symbol) | ✅ | ✅ | ✅ (from contract metadata) |
| **bid** | ✅ (`latest_quote.bid_price`) | ❌ **NOT in bars — bars are OHLCV only** | — | ✅ | ❌ **not confirmed available historically via this SDK path** |
| **ask** | ✅ (`latest_quote.ask_price`) | ❌ **NOT in bars** | — | ✅ | ❌ **same as bid** |
| last / close | ✅ (`latest_trade.price`) | ✅ (bar `close`) | — | used as fallback | ✅ |
| volume | approximated from `latest_trade.size` (see caveat below) | ✅ (bar `volume`, genuine cumulative) | — | ✅ | ✅ (bars give a **better** volume number than the live snapshot does) |
| open interest | ❌ not in live snapshot | ❌ not in bars | ✅ (`open_interest`, **lagged up to 1 day**) | ✅ | ⚠️ point-in-time only, not a historical time series |
| implied volatility | ✅ (`implied_volatility`) | ❌ not in bars | — | not used by strategy logic directly | ❌ no historical IV time series available via this path |
| delta/gamma/theta/vega | ✅ (`greeks.*`) | ❌ not in bars | — | not used by strategy logic directly | ❌ no historical Greeks time series available |

## What this means, plainly

**Alpaca's historical options data (`get_option_bars`) is OHLCV trade bars — it does not carry bid/ask, IV, Greeks, or open interest.** Those fields only exist on the *live* snapshot endpoint, which by definition has no history. This is why `scripts/fetch_historical_options.py` writes empty `bid`/`ask` columns and `data/market/csv_source.py` explicitly labels any bid=ask=last fallback as a disclosed zero-spread approximation, never a real quote.

**Practical consequence for the backtest**: a real historical dataset built purely from `get_option_bars()` cannot support a bid/ask-spread-aware fill model, cannot support IV-based strategy logic, and cannot support a historical open-interest time series. This project's strategies don't use IV/Greeks directly (they use moneyness-based strike selection), so that gap doesn't block strategy *construction* — but it does block realistic *spread cost* modeling for a real-data backtest specifically. See `backtest/data_capability.py` for the machine-readable gate that checks this before a backtest run, and returns `NOT_EVALUATABLE` rather than silently proceeding, per your explicit instruction.

**I have not verified any row of this table against a live account.** It is built from documentation, not execution.

## Sources
- `alpaca.markets/sdks/python/api_reference/data/option/historical.html` — `get_option_bars`, `get_option_chain` signatures
- `alpaca.markets/sdks/python/api_reference/data/option.html` — endpoint list (bars/trades/exchange-codes/latest-quote/latest-trade/snapshot/chain — notably no historical-quotes endpoint)
- `alpaca.markets/sdks/python/api_reference/trading/contracts.html` — `get_option_contracts`, `open_interest` field and its lag
- `alpaca.markets/learn/fetch-historical-data` — feed types (Indicative vs OPRA), 15-minute delay disclosure
- `github.com/alpacahq/alpaca-py` example notebooks — request/response shapes in practice
