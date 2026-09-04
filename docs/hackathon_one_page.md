# OptionSentinel — Hackathon One-Pager

## AI logic

OptionSentinel classifies market regime from deterministic technical features—trend, RSI, ATR, realized volatility, and momentum—not an LLM guess. Four defined-risk options strategies are eligible only in matching regimes, so the system can decline to trade rather than force a signal. Each candidate is scored across seven transparent factors: regime confidence, option signal, volatility edge, momentum, liquidity, risk/reward, and catalyst.

## Risk gates

The Risk Sentinel evaluates every candidate independently of its score across deterministic portfolio, buying-power, concentration, drawdown, daily-loss, liquidity, stale-data, duplicate-order, and contract-sanity rules. It can approve, reduce size, reject, or trigger an account-wide emergency halt. `tests/unit/test_risk.py` includes a regression that proves a high-scoring candidate can be rejected on concentration risk alone.

## Alpaca implementation

- **Trading API:** `integrations/alpaca/adapter.py` implements paper-only contract metadata pagination, option-snapshot mapping, and single-leg/2–4 leg MLEG order construction behind a `BrokerAdapter` interface.
- **Safety:** `DRY_RUN` is the default; `LIVE` is hard-blocked. `PAPER_MANUAL_APPROVAL` stops before submission, while `PAPER_AUTONOMOUS` is an explicit paper-order opt-in.
- **MCP:** `integrations/alpaca_mcp/client.py` is an optional agent-session seam, not a pipeline dependency.
- **CLI:** `integrations/alpaca_cli/cli.py` offers optional diagnostics without becoming a runtime dependency.

The adapter has offline SDK-shape coverage, but its authenticated paper endpoint behavior has not yet been manually exercised and no paper order has been placed for this project handoff.

## Innovation

Many trading-agent demos ask an LLM for a direction and execute it. OptionSentinel keeps the numerical decision path—regime, strategy, scoring, sizing, and risk—deterministic and independently testable. LLM use is limited to optional explanation; it cannot override the Risk Sentinel.

## Synthetic evaluation

A fixed-seed synthetic comparison is documented in [reports/performance.md](../reports/performance.md). It is **not** paper-account, live, or historical-options P&L.

| Metric | OptionSentinel | Buy and hold |
|---|---:|---:|
| Period | 2025-06-01 to 2026-03-20 | Same warmup-adjusted window |
| Total result | $1,637 realized P&L (1.64% of $100,000) | -16.25% return |
| Completed trades | 20 | N/A |
| Win rate | 50.0% | N/A |
| Maximum drawdown | 2.74% realized-equity drawdown | 28.22% |

The strategy sample ended with eight open positions, uses a hold-to-expiration model, and uses synthetic option quotes. It is useful only as a reproducible systems test and comparison artifact, not evidence of expected returns. The report records capability status, cost assumptions, leakage/survivorship tests, and all limitations.

## What remains to measure

Actual paper-trading metrics remain intentionally unreported until a separate read-only paper-account validation and an explicitly approved paper-execution experiment have occurred. Those future measurements should include realized P&L, win rate, observed drawdown, trade frequency, strategy contribution, and prevented-risk verdicts from persisted audit data.
