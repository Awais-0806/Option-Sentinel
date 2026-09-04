# OptionSentinel — Architecture

## Pipeline

```text
MARKET DATA
    |
    v
MARKET REGIME  (agents/regime/classifier.py)
    |
    v
OPTIONS ANALYSIS  (BrokerAdapter option chain, liquidity filtering)
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
RISK SENTINEL  (risk/veto.py — final authority)
    |
    v
EXECUTION  (BrokerAdapter.submit_order, mode-gated)
    |
    v
JOURNAL  (core/models/trade.py; persistence models are not yet wired)
```

`core/orchestration/pipeline.py::run_pipeline` implements the end-to-end flow.

## Agent responsibilities

| Agent | Module | Responsibility |
|---|---|---|
| Market Scout | pipeline scan loop | Fetches bars and option chains through `BrokerAdapter` |
| Regime Analyst | `agents/regime/classifier.py` | BULLISH, BEARISH, RANGE, HIGH_VOLATILITY, LOW_VOLATILITY, or UNCERTAIN classification |
| Options Analyst | `agents/options_analyst/`, option models | Contract quality and liquidity filtering |
| Strategy Agent | `agents/strategy/selector.py`, `strategies/` | Eligibility, trade construction, and rationale |
| Risk Sentinel | `risk/limits.py`, `risk/veto.py`, `risk/circuit_breaker.py` | APPROVE, REDUCE_SIZE, REJECT, or EMERGENCY_HALT |
| Execution Agent | `integrations/alpaca/adapter.py` | Paper-only order construction and submission |
| Portfolio Monitor | `BrokerAdapter.get_account()` | Equity, buying power, daily P&L, and drawdown |
| Exit Agent | Not implemented | Positions use the documented hold-to-expiration backtest model |

## Deterministic versus LLM-assisted work

**Deterministic:** regime classification, trade scoring, all strategy construction, position sizing, every risk rule, the circuit breaker, and execution-mode gates. These components are pure Python/numpy and are unit tested.

**LLM-assisted seam, not wired into execution:** human-readable rationale expansion, trade-journal summarization, and anomaly explanation. An LLM is never between a candidate trade and a risk verdict.

## Broker boundary

`core/interfaces/broker.py::BrokerAdapter` isolates the application from Alpaca. The mock adapter supports safe offline development. `integrations/broker_factory.py::get_broker_adapter` is the sole real-versus-mock selector:

- `DRY_RUN` and `PAPER_SIMULATION` always return `MockBrokerAdapter`.
- `PAPER_MANUAL_APPROVAL` and `PAPER_AUTONOMOUS` require non-placeholder paper credentials and return `AlpacaBrokerAdapter`.
- `LIVE` always raises `LiveTradingDisabledError`.

The paper adapter retrieves paginated option-contract metadata, retrieves option snapshots, maps both to internal contracts, and constructs single-leg or 2–4 leg MLEG orders. SDK request construction and mapping are covered offline, and a read-only `PAPER_MANUAL_APPROVAL` check retrieved a paper-account snapshot. Option-chain data, market-data entitlements, and paper-order submission remain unverified.

## Safety gates

1. **Paper-only adapter:** `AlpacaBrokerAdapter` rejects every non-paper endpoint at construction. It always initializes Alpaca’s trading client with `paper=True`.
2. **Live mode:** `ExecutionMode.LIVE` is hard-blocked by the broker factory and cannot create an adapter. No confirmation flag can enable it.
3. **Execution mode:** the default is `DRY_RUN`. The mode controls both adapter selection and `pipeline._maybe_submit` behavior; credential strings never alter this selection.
4. **Manual approval:** `PAPER_MANUAL_APPROVAL` builds and risk-checks a trade, then returns `AWAITING_MANUAL_APPROVAL` without submission. There is no approval UI or CLI yet.
5. **Autonomous paper submission:** only `PAPER_AUTONOMOUS` calls `broker.submit_order`, and only after a non-rejecting Risk Sentinel decision. This is explicit operator opt-in and is not used by the demo.
6. **Additional risk controls:** duplicate-order checks, liquidity and contract validation, concentration limits, buying-power checks, and circuit breakers apply independently of model scores.
7. **Test-level order gate:** `tests/integration/test_alpaca_adapter.py` requires `OPTIONSENTINEL_ALLOW_ORDER_TEST=1` in addition to paper credentials. Its order-submission seam is intentionally still a no-op.

## Data model and audit trail

`data/persistence/models.py` defines `MarketScan`, `Opportunity`, `RiskCheck`, `Order`, `Position`, `PnLSnapshot`, and `SystemEvent`. `data/persistence/repository.py` maps internal dataclasses to those rows. SQLite is the default target, but pipeline runs currently return an in-memory `PipelineResult` rather than persisting the journal.

## Configuration

`core/config/settings.py::Settings` is the source of truth for risk thresholds, scoring weights, deployment stage, execution mode, and credentials. Standard Alpaca variables `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` are primary; `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` remain supported aliases. Defaults are `ALPACA_ENV=paper` and `EXECUTION_MODE=DRY_RUN`.

## Alpaca data notes

The integration uses `alpaca-py>=0.44.0` and is validated offline against the SDK request and mapping surface. That validation confirms import and construction compatibility only; it does **not** prove authenticated paper API responses, entitlement behavior, or order acceptance.

- Contract metadata supplies strike, expiration, right, and lagged open interest through `get_option_contracts`.
- Option snapshots supply quotes, latest trade, IV, and Greeks through the option data client.
- Open interest may lag by up to one day.
- `latest_trade.size` is used as a latest-print volume proxy, not confirmed cumulative daily volume.
- Historical option bars are OHLCV only. They do not provide historical bid/ask, IV, Greeks, or an open-interest series; see [ALPACA_DATA_CAPABILITY_MATRIX.md](ALPACA_DATA_CAPABILITY_MATRIX.md).

## MCP and CLI seams

The core engine does not depend on an interactive session. `integrations/alpaca_mcp/client.py` documents an optional MCP integration seam, while `integrations/alpaca_cli/cli.py` optionally checks the Alpaca CLI. Neither is required to run the pipeline.
