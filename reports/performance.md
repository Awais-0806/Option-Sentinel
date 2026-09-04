# Synthetic performance report

## Scope and reproducibility

This is a **fixed-seed synthetic-data experiment**, not paper trading, live trading, or a historical-options-data result. It is suitable for exercising the deterministic decision, risk, and accounting paths; it is not evidence of an investable edge or a forecast of market performance.

Run from the repository root with the project virtual environment:

```bash
venv/Scripts/python.exe -m scripts.run_backtest \
  --symbol SPY \
  --start 2025-06-01 \
  --end 2026-03-20 \
  --data synthetic
```

Configuration: `$100,000` starting equity and a 55-trading-day warmup. The generated dataset contains business days from 2025-06-02 through 2026-03-19. The command writes `data/historical/backtest_report_SPY_2025-06-01_2026-03-20_synthetic.json`; that directory is ignored because it may also contain local market-data captures.

Two consecutive runs with those inputs produced byte-identical report files. SHA-256 of the verified output:

```text
4524d49c1a53ca87c065fd4e9f48f1ba698b67230ad989757f5aeb1627098d67
```

`tests/backtest/test_reproducibility.py` verifies deterministic data generation and backtest statistics. `tests/backtest/test_run_backtest_report.py` verifies that the CLI report has no wall-clock field, includes buy-and-hold, honors starting equity, and serializes identically across two runs.

## Data capability and modeling assumptions

The report classifies this dataset as `EVALUATABLE_WITH_CAVEATS`:

- Underlying prices follow a synthetic GBM path; option prices use Black-Scholes-Merton with a 4.5% risk-free rate and trailing 20-day realized volatility, with no volatility smile.
- The chain uses strikes from 80% to 120% moneyness and 21, 33, and 42 DTE expirations.
- Bid/ask quotes are model-generated as fair value plus or minus a fixed 4% spread. They are not market quotes.
- The base cost model uses $0.65 per contract at both entry and expiration and no additional slippage; buy legs pay ask and sell legs receive bid. The conservative sweep uses $1.00 per contract and 2% extra slippage; the optimistic sweep uses no commission or extra slippage.
- Positions use `HOLD_TO_EXPIRATION`; no early-exit rule is enabled. The reported strategy P&L and drawdown use completed trades only. Positions open on the sample cutoff are listed below and are not treated as completed P&L.

The replay safeguards are covered by `tests/backtest/test_replay_engine_leakage.py`; its mutation test ensures future observations cannot change an earlier decision. `tests/backtest/test_leakage_phase6.py` also checks the point-in-time universe to guard against survivorship bias in the replay interface. These tests validate backtest mechanics, not real-world predictive performance.

## Results

All percentages below are percentages, not fractions. `PF` is profit factor; `Open` is the count of positions still open at the sample end.

| Strategy | Completed | Win rate | Avg P&L | Median P&L | Total P&L | Max drawdown | PF | Avg winner | Avg loser | Open |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OptionSentinel | 20 | 50.00% | $81.85 | -$90.60 | $1,637.00 | 2.74% | 1.5378 | $468.10 | -$304.40 | 8 |
| Always Bull Call | 24 | 12.50% | -$223.73 | -$315.10 | -$5,369.40 | 5.83% | 0.1788 | $389.73 | -$311.36 | 7 |
| Always Bear Put | 33 | 48.48% | $31.82 | -$142.60 | $1,050.20 | 3.57% | 1.2274 | $354.34 | -$271.72 | 8 |
| Always Iron Condor | 38 | 71.05% | $88.72 | $234.30 | $3,371.40 | 1.68% | 2.0538 | $243.36 | -$290.84 | 8 |
| Simple Regime Selector | 20 | 50.00% | $66.40 | -$90.60 | $1,328.00 | 2.75% | 1.4363 | $437.20 | -$304.40 | 8 |

The OptionSentinel path produced 55 signals: 28 were risk-approved, 27 were risk-rejected, none were reduced, and none became `NO_TRADE`. Its 49.09% rejection rate is a Risk Sentinel result, not a post-hoc filter.

### Buy-and-hold benchmark

The benchmark begins after the same 55-day warmup, on 2025-08-18, and ends on 2026-03-19. It buys $100,000 of the synthetic underlying at $178.34 and holds 560.7267 shares through an end price of $149.36.

| Starting equity | Ending equity | P&L | Return | Max drawdown |
|---:|---:|---:|---:|---:|
| $100,000.00 | $83,750.14 | -$16,249.86 | -16.25% | 28.22% |

This comparison is descriptive within one simulated path. It does not establish outperformance, risk-adjusted returns, or expected live results.

### OptionSentinel cost sensitivity

| Cost setting | Completed | Total P&L | Win rate | Max drawdown | PF | Open |
|---|---:|---:|---:|---:|---:|---:|
| Optimistic: $0 commission, 0% extra slippage | 20 | $1,689.00 | 50.00% | 2.71% | 1.5596 | 8 |
| Base: $0.65/contract, 0% extra slippage | 20 | $1,637.00 | 50.00% | 2.74% | 1.5378 | 8 |
| Conservative: $1.00/contract, 2% extra slippage | 20 | $1,293.34 | 50.00% | 2.94% | 1.4008 | 8 |

## Interpretation limits

- This is one deterministic scenario with 20 completed OptionSentinel trades, not a statistically sufficient sample or a parameter-selection exercise.
- Synthetic bid/ask, volatility, and underlying paths cannot model quote availability, volatility smiles/skews, real liquidity, assignment, corporate actions, halts, data outages, or market-impact effects.
- Historical Alpaca option bars do not supply historical bid/ask, IV, Greeks, or full open-interest history. The capability gate refuses unsupported historical evaluations rather than inventing those values; see `docs/ALPACA_DATA_CAPABILITY_MATRIX.md`.
- No authenticated Alpaca paper-account order has been placed for this report. Live execution is permanently blocked by the application.
