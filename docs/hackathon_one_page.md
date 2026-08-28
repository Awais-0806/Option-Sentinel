# OptionSentinel — Hackathon One-Pager (Draft)

*Status: Day 1 draft. Sections marked [MEASURE] need real numbers from a
paper-trading run before submission — nothing below is fabricated, and
nothing should be filled in with invented performance figures later either.*

## AI logic

OptionSentinel classifies market regime from price history using deterministic technical features (trend, RSI, ATR, realized volatility, momentum) — not an LLM guess. Four defined-risk options strategies are each eligible only under specific regime conditions, so the system doesn't force a trade when conditions don't fit. Every candidate trade is scored transparently across seven weighted factors (regime confidence, options signal, volatility edge, momentum, liquidity, risk/reward, catalyst).

## Risk gates

The Risk Sentinel evaluates every trade candidate independently of its score, across 13 deterministic rules — buying power, trade/portfolio risk limits, concentration, drawdown, daily loss, liquidity, duplicate-order prevention, stale-data detection, and more. It can approve, reduce size, reject, or trip an account-wide emergency halt. A high score does not bypass this layer: `tests/unit/test_risk.py` includes a direct regression test where a trade candidate is rejected purely on concentration risk regardless of its score.

## Alpaca implementation

- **Trading API**: `integrations/alpaca/adapter.py`, behind a `BrokerAdapter` interface so the entire engine is broker-agnostic in principle and Alpaca-specific in practice for this build.
- **MCP**: documented integration seam (`integrations/alpaca_mcp/client.py`) for agent-driven sessions; not on the autonomous pipeline's critical path by design.
- **CLI**: health-check and diagnostics (`integrations/alpaca_cli/cli.py`), optional, never a hard dependency.

## Innovation

Most "AI trading agent" hackathon entries ask an LLM "buy or sell?" and execute the answer. OptionSentinel's numerical decision path — regime, scoring, sizing, risk — is 100% deterministic and independently unit-tested; the LLM (where used) narrates and explains, never decides. The Risk Sentinel's veto is a first-class, demoable feature, not a disclaimer: it appears in the structured event log and the trade journal every time it fires.

## Evaluation

[MEASURE] The following will be reported from an actual paper-trading run before submission, not estimated in advance:

- P&L (realized, from the trade journal)
- Win rate and average trade
- Max drawdown observed during the run
- Trade frequency (opportunities scanned vs. trades approved vs. trades rejected)
- Strategy-level contribution (which of the four strategies fired, how often, with what outcome)
- Risk violations prevented — count of REJECT / REDUCE_SIZE / EMERGENCY_HALT verdicts, with reasons, pulled directly from `risk_checks` in the audit trail

No performance numbers are fabricated in this document. Where a section says [MEASURE], it stays empty until there is a real run to report.
