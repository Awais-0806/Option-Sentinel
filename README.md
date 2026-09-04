# OptionSentinel

**A regime-aware, defined-risk options system with an independent Risk Sentinel veto.**

Built for the Alpaca AI Trading Agents Hackathon.

## What it does

OptionSentinel classifies market conditions with deterministic technical signals, selects one of four defined-risk options strategies, scores each candidate transparently, and sends every candidate through a separate, LLM-free Risk Sentinel. A high score never overrides portfolio, liquidity, concentration, drawdown, or circuit-breaker rules.

| Strategy | Eligible regime | Risk profile |
|---|---|---|
| Bull Call Spread | BULLISH | Defined-risk debit spread |
| Bear Put Spread | BEARISH | Defined-risk debit spread |
| Iron Condor | RANGE with elevated IV | Defined-risk credit spread |
| Long Volatility | HIGH_VOLATILITY with high confidence | Capped debit |

The numerical decision path—regime classification, scoring, sizing, strategy construction, and risk verdicts—is deterministic code. An LLM is only an optional explanatory seam and is never in the execution decision path.

## Paper-only safety boundary

`EXECUTION_MODE` is the only selector for the broker adapter and submission behavior:

| Mode | Data/account adapter | Submission behavior |
|---|---|---|
| `DRY_RUN` (default) | Deterministic mock | Never submits or calls Alpaca |
| `PAPER_SIMULATION` | Deterministic mock | Never submits or calls Alpaca |
| `PAPER_MANUAL_APPROVAL` | Real Alpaca paper adapter | Builds and risk-checks trades, then stops before submission |
| `PAPER_AUTONOMOUS` | Real Alpaca paper adapter | Can submit approved orders to an Alpaca **paper** account |
| `LIVE` | None | Hard-blocked unconditionally |

The adapter refuses every non-paper endpoint, and `LIVE` raises before an adapter can be created. No flag, credential, or confirmation value enables live trading in this build. For a safe demo, leave `EXECUTION_MODE=DRY_RUN`.

## Alpaca integration

The `BrokerAdapter` protocol keeps the engine separate from Alpaca-specific code. The paper adapter:

- retrieves paginated active option-contract metadata and combines it with option snapshots;
- maps quote, trade, Greeks, IV, and metadata fields into the internal option model;
- builds one-leg market orders and 2–4 leg MLEG orders; and
- maps malformed requests and broker failures to rejected order results.

Offline adapter mapping tests and a read-only `PAPER_MANUAL_APPROVAL` paper-account check have succeeded. Option-chain data, market-data entitlements, and paper-order submission remain unverified; no paper order has been placed as part of this project handoff.

## Local setup

```bash
git clone <this-repo>
cd optionsentinel
cp .env.example .env
make dev-install
make health
```

The default `.env` is safe: `ALPACA_ENV=paper` and `EXECUTION_MODE=DRY_RUN`. `make health` uses the mock adapter in either mock mode and makes no network calls.

To use a real Alpaca **paper** account, set exactly one supported credential scheme in `.env`:

```dotenv
APCA_API_KEY_ID=your_paper_key
APCA_API_SECRET_KEY=your_paper_secret
# Legacy aliases also work: ALPACA_API_KEY and ALPACA_SECRET_KEY.
```

Then explicitly set `EXECUTION_MODE=PAPER_MANUAL_APPROVAL` for read-only pipeline validation. Do not use `PAPER_AUTONOMOUS` for the demo; it is the only mode that can submit a paper order.

## Tests and checks

```bash
make test-unit
make test-backtest
make test-sim
pytest -v --ignore=tests/integration  # complete offline suite
make lint
```

Credentialed checks are opt-in and separate:

```bash
make test-integration
```

The integration suite auto-skips without credentials. Its order-submission test has a second explicit environment gate and is intentionally a documented no-op until a manual approval workflow exists.

## API demo

Start the local API with the safe default:

```bash
make run
```

In another terminal:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/account
curl -X POST http://127.0.0.1:8000/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"symbols":["SPY"]}'
```

In `DRY_RUN`, `/health` and `/pipeline/run` report `data_source: "MOCK"`; the pipeline exercises the same deterministic strategy and Risk Sentinel code without contacting Alpaca.

## Backtest

Run the fixed-seed synthetic experiment:

```bash
python -m scripts.run_backtest \
  --symbol SPY \
  --start 2025-06-01 \
  --end 2026-03-20 \
  --data synthetic
```

The command writes a deterministic JSON report to `data/historical/` with strategy metrics, cost sensitivity, and a matching buy-and-hold benchmark. The directory is intentionally ignored because it can contain fetched local market data. See [reports/performance.md](reports/performance.md) for the exact synthetic comparison, assumptions, and limitations.

## Three-to-five-minute demo

1. Run `make health` and show `EXECUTION_MODE: DRY_RUN` with a mock source.
2. Start the API, call `/health` and `/account`, then run `POST /pipeline/run` for `SPY`.
3. Walk through the pipeline summary and one candidate’s Risk Sentinel verdict; explain that a strong score still cannot bypass risk controls.
4. Run `make test-backtest` or the synthetic backtest command and open `reports/performance.md`.
5. Point out the execution-mode table: the demo is mock-only, paper execution is explicit, and live execution is impossible in this build.

## Known limitations

- A read-only `PAPER_MANUAL_APPROVAL` check successfully retrieved a paper-account snapshot. Option-chain behavior, market-data entitlements, and order submission remain unverified; offline SDK-shape tests are not a replacement for those checks.
- Snapshot `latest_trade.size` is a latest-print proxy, not confirmed cumulative daily option volume.
- Alpaca historical option bars omit historical bid/ask, IV, Greeks, and open-interest series. The backtest capability gate refuses unsupported data rather than inventing those fields; see [docs/ALPACA_DATA_CAPABILITY_MATRIX.md](docs/ALPACA_DATA_CAPABILITY_MATRIX.md).
- There is no dashboard, persistence wiring for pipeline runs, or live exit-management workflow. Positions in the default backtest hold to expiration; positions still open at the sample end are reported separately.
- There is no manual-approval UI or CLI. `PAPER_MANUAL_APPROVAL` intentionally stops before submission.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the pipeline, safety gates, data caveats, and deterministic/LLM boundary.

## License

MIT — see `LICENSE`.
