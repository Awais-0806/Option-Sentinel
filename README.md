# OptionSentinel

**An autonomous options trader that thinks in regimes, trades in defined risk, and gives the Risk Sentinel the final veto.**

Built for the Alpaca AI Trading Agents Hackathon.

## What is OptionSentinel?

OptionSentinel is a regime-aware, multi-agent autonomous options trading system. It classifies market conditions with deterministic technical signals (not an LLM guess), selects from four defined-risk options strategies, scores each candidate trade transparently, and — critically — runs every candidate through a **Risk Sentinel** with independent, LLM-free veto authority. A high trade score does not guarantee execution; the Risk Sentinel can and does reject trades that score well but violate portfolio-level risk limits.

## Why it's different

Most LLM trading bot demos ask a language model "should I buy this?" and act on the answer. OptionSentinel doesn't. The number-crunching — regime classification, trade scoring, position sizing, risk limits, duplicate-order prevention — is all deterministic code. The LLM layer (where used) explains and narrates; it never decides. See `docs/ARCHITECTURE.md` for the full breakdown of what's deterministic vs. LLM-assisted.

## How autonomous agents work

```
Market Scout → Regime Analyst → Options Analyst → Strategy Agent
    → Risk Sentinel → Execution Agent → Portfolio Monitor → Exit Agent
```

Each stage is a separate, testable module. `core/orchestration/pipeline.py` wires them together for the end-to-end dry run. See `docs/ARCHITECTURE.md` for what each agent owns.

## How options strategies work

Four strategies, each strategy-eligible only under specific regime conditions:

| Strategy | Eligible regime | Risk profile |
|---|---|---|
| Bull Call Spread | BULLISH | Defined risk, debit |
| Bear Put Spread | BEARISH | Defined risk, debit |
| Iron Condor | RANGE + elevated IV | Defined risk, credit |
| Long Volatility (straddle) | HIGH_VOLATILITY, high confidence only | Defined risk on entry, capped debit |

The system is deliberately selective — see `strategies/long_volatility.py` for the strictest example; it will not fire on every high-volatility reading, only on high-confidence ones, per the "strict maximum-risk control" requirement.

## How risk controls work

`risk/limits.py` defines 13 independent, deterministic rules (buying power, max trade/portfolio risk, concentration, drawdown, daily loss, liquidity, duplicate orders, stale data, contract sanity, and more). `risk/veto.py`'s `RiskSentinel` runs all of them and issues one of four verdicts:

- **APPROVE** — trade proceeds as sized
- **REDUCE_SIZE** — trade proceeds at a smaller, affordable quantity
- **REJECT** — trade is blocked, with itemized reasons
- **EMERGENCY_HALT** — account-wide circuit breaker trips (drawdown, daily loss, or repeated rejections); no new entries regardless of trade quality

This is independently tested in `tests/unit/test_risk.py`, including a direct regression test proving a high-scoring trade can still be rejected on concentration risk.

## How Alpaca is integrated

`core/interfaces/broker.py` defines a `BrokerAdapter` Protocol. Nothing in `agents/`, `strategies/`, `risk/`, or `core/orchestration/` imports Alpaca directly — they depend only on this interface. Two implementations exist:

- `integrations/alpaca/adapter.py` — real Alpaca paper/live REST calls via `alpaca-py`
- `integrations/alpaca/mock_adapter.py` — deterministic synthetic data, used by default in `DRY_RUN` and by every test in this repo

This means the exact same pipeline code runs whether you have credentials configured or not.

## How MCP is integrated

`integrations/alpaca_mcp/client.py` documents the seam for driving OptionSentinel's data through an MCP-connected agent session. The autonomous pipeline itself does not depend on MCP — see `docs/ARCHITECTURE.md`, "MCP Architecture."

## How CLI is integrated

`integrations/alpaca_cli/cli.py` detects and health-checks the Alpaca CLI if installed (`alpaca version`, `alpaca doctor`). The application never depends on the CLI being present — `python -m scripts.health_check` reports clearly if it's missing, with an install hint, and continues.

## How to run locally

```bash
git clone <this-repo>
cd optionsentinel
cp .env.example .env          # defaults are safe — paper env, DRY_RUN mode
make install                  # or: pip install -e . --break-system-packages
make health                   # python -m scripts.health_check
```

With no credentials configured, `health` and the pipeline both fall back to the mock adapter automatically — you can exercise the full system before ever touching Alpaca.

Once you have paper credentials, add them to `.env` and re-run `make health` — it will report real `ALPACA_CONNECTION` / `ACCOUNT` / `MARKET_DATA` status. `OPTIONS_DATA` retrieval against the real API is not yet implemented (see Known Limitations).

## How to use paper trading

`ALPACA_ENV=paper` in `.env` (default). The system refuses to run against a live endpoint unless **both** `ALPACA_ENV=live` and `ALPACA_LIVE_TRADING_CONFIRMED=true` are set — and even then, no live order path is implemented in this build. See `integrations/alpaca/adapter.py`'s `LiveTradingDisabledError`.

## How to run tests

```bash
make dev-install
make test           # everything
make test-unit      # regime, scoring, risk, strategies, failure modes
make test-sim        # full offline dry-run pipeline
make test-integration  # requires real paper credentials; auto-skips otherwise
```

## How to enable dry-run / how to safely execute paper trades

`EXECUTION_MODE` in `.env` has three values:

- `DRY_RUN` (default) — full pipeline runs, nothing touches Alpaca, everything is journaled
- `SIMULATION` — orders are priced/validated against live quotes but never submitted
- `PAPER_EXECUTION` — orders are actually submitted to your Alpaca **paper** account

The operator must explicitly change `EXECUTION_MODE` — the system never escalates itself.

## Architecture diagram

See `docs/ARCHITECTURE.md`.

## Demo flow

1. `make health` — show Alpaca/CLI connectivity
2. `python -c "from core.orchestration.pipeline import run_pipeline; ..."` (or hit `POST /pipeline/run` once `make run` is up) across the watchlist
3. Walk through the resulting trade journal — highlight at least one `APPROVE` and one `REJECT`/`REDUCE_SIZE` to demonstrate the veto
4. Show `tests/unit/test_risk.py::test_high_score_trade_can_still_be_rejected_on_concentration` passing live

## Known limitations (Day 1, honest accounting)

- Real Alpaca **option chain** retrieval (`integrations/alpaca/adapter.py::get_option_chain`) is stubbed — needs real paper credentials to build and verify against actual response shapes. The mock adapter's synthetic chain generator stands in for it everywhere else.
- Real order submission (`AlpacaBrokerAdapter.submit_order`) is stubbed for the same reason — multi-leg options order construction needs to be verified against live paper responses before it's trustworthy.
- No frontend dashboard yet — `apps/api/main.py` exposes the JSON endpoints (`/health`, `/account`, `/pipeline/run`) a dashboard would consume, but no UI is built.
- Persistence layer (`data/persistence/`) is fully modeled but not yet wired into the live pipeline run — currently the pipeline returns an in-memory `PipelineResult`.
- News/catalyst scoring input is a placeholder (always 0) — no news feed is wired in yet.
- `probability_estimate` is currently always `None` — no probability-of-profit model has been built.

## License

MIT — see `LICENSE`.
