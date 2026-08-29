# OptionSentinel — Architecture

## Pipeline

```
MARKET DATA
    |
    v
MARKET REGIME  (agents/regime/classifier.py)
    |
    v
OPTIONS ANALYSIS  (option chain from BrokerAdapter, filtered by liquidity)
    |
    v
STRATEGY SELECTION  (agents/strategy/selector.py)
    |
    v
TRADE CONSTRUCTION  (strategies/*.py)
    |
    v
TRADE SCORING  (agents/strategy/scoring.py)
    |
    v
RISK SENTINEL  (risk/veto.py) <-- final authority, independent of score
    |
    v
EXECUTION  (BrokerAdapter.submit_order, mode-gated)
    |
    v
JOURNAL  (core/models/trade.py::TradeJournalEntry, data/persistence/)
```

Implemented end-to-end in `core/orchestration/pipeline.py::run_pipeline`.

## Agent responsibilities

| Agent | Module | Owns |
|---|---|---|
| Market Scout | (folded into `pipeline.py` scan loop) | fetches bars/chain per symbol via `BrokerAdapter` |
| Regime Analyst | `agents/regime/classifier.py` | BULLISH/BEARISH/RANGE/HIGH_VOL/LOW_VOL/UNCERTAIN classification |
| Options Analyst | `core/models/options.py` + strategy contract filters | contract quality (spread, OI, volume) |
| Strategy Agent | `agents/strategy/selector.py`, `strategies/*.py` | strategy eligibility, trade construction, rationale |
| Risk Sentinel | `risk/limits.py`, `risk/veto.py`, `risk/circuit_breaker.py` | APPROVE / REDUCE_SIZE / REJECT / EMERGENCY_HALT |
| Execution Agent | `integrations/alpaca/adapter.py` | order submission (paper-only; stubbed pending credential verification) |
| Portfolio Monitor | `core/interfaces/broker.py::AccountSnapshot` | equity, buying power, daily P&L, drawdown |
| Exit Agent | not yet implemented | see Known Limitations in README |

## Deterministic vs. LLM-assisted

**Deterministic (pure Python/numpy, zero LLM calls, fully unit-tested):**
- Regime classification (`agents/regime/classifier.py`)
- Trade scoring (`agents/strategy/scoring.py`)
- All four strategy construction algorithms (`strategies/*.py`)
- Every risk rule (`risk/limits.py`) and the veto decision (`risk/veto.py`)
- Position sizing (`risk/sizing.py`) and the circuit breaker (`risk/circuit_breaker.py`)

**LLM-assisted (not yet wired in this build, documented as the intended seam):**
- Natural-language rationale expansion for the dashboard (the strategies already produce a machine-generated `rationale` string; an LLM could rephrase/expand it for a human audience without touching the underlying numbers)
- Trade journal summarization across a trading session
- Anomaly interpretation when the circuit breaker trips

The dividing line is intentional and load-bearing for the "not just an LLM trading bot" claim: an LLM is never in the call path between "here is a trade candidate" and "here is a risk verdict."

## MCP Architecture

```
AI Agent (interactive/desktop session)
    -> Alpaca MCP server
    -> Alpaca Trading API
```

The core engine does **not** depend on this path — it would create a hard dependency on an interactive desktop session, which conflicts with "autonomous application." Instead:

```
Core engine          -> Alpaca adapter (integrations/alpaca/adapter.py)
Optional agent UI     -> Alpaca MCP    (integrations/alpaca_mcp/client.py)
Automation/inspection -> Alpaca CLI    (integrations/alpaca_cli/cli.py)
```

`integrations/alpaca_mcp/client.py` is a documented seam, not a hard dependency in `pyproject.toml` — MCP client libraries vary by what the operator has installed locally.

## Data model / audit trail

`data/persistence/models.py` defines the full audit trail: `MarketScan`, `Opportunity`, `RiskCheck`, `Order`, `Position`, `PnLSnapshot`, `SystemEvent`. `data/persistence/repository.py` translates the in-memory dataclasses in `core/models/` into these rows. SQLite by default (`DATABASE_URL` in `.env`); the repository layer is the only place that would need to change to move to Postgres.

## Configuration

Every threshold — risk limits, scoring weights, size-tier cutoffs — lives in `core/config/settings.py` (`Settings`, backed by `pydantic-settings` reading `.env`). No other module hardcodes a limit; this is what makes "the thresholds are configurable" in the spec actually true rather than aspirational.

## Safety gates

1. **Live trading**: `AlpacaBrokerAdapter.__init__` raises `LiveTradingDisabledError` unless both `ALPACA_ENV=live` and `ALPACA_LIVE_TRADING_CONFIRMED=true` are set — and even then, `submit_order` raises `LiveTradingDisabledError` unconditionally, because no live order path is implemented yet.
2. **Execution mode**: `EXECUTION_MODE` defaults to `DRY_RUN`. Adapter selection (`integrations/broker_factory.py`) and order-submission gating (`core/orchestration/pipeline.py::_maybe_submit`) both key off this single setting — `DRY_RUN`/`PAPER_SIMULATION` never touch Alpaca, `PAPER_MANUAL_APPROVAL` builds and risk-checks real trades but stops before submission, `PAPER_AUTONOMOUS` submits approved trades, and `LIVE` is hard-blocked unconditionally.
3. **Duplicate orders**: every risk check includes a `client_order_id` uniqueness check against recently-seen IDs.
4. **Circuit breaker**: independent of any single trade — trips on drawdown breach, daily loss breach, repeated risk rejections, or an externally-flagged abnormal-market condition.
5. **Order-submission test gating**: `tests/integration/test_alpaca_adapter.py` requires a second, independent opt-in (`OPTIONSENTINEL_ALLOW_ORDER_TEST=1`) beyond credentials before any order-submission code path can even be exercised in tests — and as of Phase C, that path is still a documented no-op pending the manual-approval flow (Phase E).

## Alpaca API grounding notes (Phase C)

`integrations/alpaca/adapter.py`'s real implementation is grounded in Alpaca's own current official example notebooks and docs (researched via web search; not from training-data memory, since options-trading SDK surfaces change quickly):

- Contract metadata (strike, expiration, type, open interest): `TradingClient.get_option_contracts(GetOptionContractsRequest(...))` — source: `alpaca.markets/sdks/python/api_reference/trading/contracts.html`, `docs.alpaca.markets/us/docs/options-trading`.
- Live quotes/greeks/IV: `OptionHistoricalDataClient.get_option_chain(OptionChainRequest(...))` returning `Dict[str, OptionsSnapshot]` — source: `alpaca.markets/sdks/python/api_reference/data/option/historical.html`, `alpaca.markets/sdks/python/api_reference/data/models.html`.
- Multi-leg order submission: `MarketOrderRequest`/`LimitOrderRequest` with `order_class=OrderClass.MLEG` and `legs=[OptionLegRequest(symbol=..., side=..., ratio_qty=...)]` — source: `github.com/alpacahq/alpaca-py` example notebooks `options-bull-call-spread.ipynb` and `options-iron-condor.ipynb` (both current on `master` as of this research).

**Two known, documented caveats in the current implementation** (not silently assumed away):
- **Open interest has up to a 1-day lag.** Alpaca computes it from OCC end-of-day data, not live — the contract-metadata endpoint's own response includes an `open_interest_date` field for exactly this reason. Our normalized `OptionContract` does not currently carry that date through; the Risk Sentinel and validator treat the OI number as current, which is a known small inaccuracy.
- **`volume` is mapped from `latest_trade.size`** (the most recent single print), not a confirmed cumulative-daily-volume field — the snapshot endpoint's exact volume semantics need verification against a live account. True daily volume may require aggregating `get_option_bars()` instead.

**What this grounding does and doesn't mean**: the code above was written against current, cited, official documentation and example code — not guessed, not copied from a possibly-stale training memory. It has NOT been executed against a live Alpaca paper account by Claude (no network/credentials in the sandbox this was built in). It needs to be run against a real account before anyone should trust it. See the Phase C human test plan for exactly how.
