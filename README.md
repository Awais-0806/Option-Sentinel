# 🦂 OptionSentinel

### Autonomous, Regime-Aware Options Trading Agent with Deterministic Risk Control

**Team Scorpion**
**Awais Jabbar · Muhammad Ekremah · Alveena Haneef**

> **AI proposes. Risk Sentinel decides.**

OptionSentinel is an autonomous options trading agent built for the **Alpaca AI Trading Agents Hackathon**. It combines deterministic market analysis, defined-risk options strategies, transparent trade scoring, and an independent **Risk Sentinel** that can veto any proposed trade before execution.

The system is designed around one core principle:

**The AI can propose a trade, but it cannot bypass the risk engine.**

All critical trading decisions — market-regime classification, strategy eligibility, trade scoring, position sizing, risk limits, duplicate-order prevention, and execution gating — are handled through deterministic code.

The optional LLM layer is limited to explanation and narration. It does **not** make trading decisions.

---

## 🚀 Key Features

* 📊 **Deterministic market-regime detection**
* 🤖 **Multi-agent trading pipeline**
* 📈 **Four defined-risk options strategies**
* 🛡️ **Independent Risk Sentinel with veto authority**
* 🎯 **Transparent candidate trade scoring**
* 💰 **Deterministic position sizing**
* 🔒 **Portfolio-level and account-level risk controls**
* 🔁 **Duplicate-order prevention**
* 🧪 **Offline mock broker for testing**
* ☁️ **Alpaca paper-trading integration**
* 🧩 **Broker abstraction through a clean interface**
* ⚙️ **CLI and MCP integration seams**
* 📝 **Trade journaling and auditable risk decisions**
* 🚨 **Emergency account-wide trading halt**
* 🧑‍💻 **Fully testable modular architecture**

---

# 🧠 What is OptionSentinel?

OptionSentinel is a **regime-aware, multi-agent options trading system**.

Instead of allowing an LLM to directly determine whether a trade should be executed, the system separates intelligence from execution authority.

The pipeline:

```text
Market Data
     ↓
Market Scout
     ↓
Regime Analyst
     ↓
Options Analyst
     ↓
Strategy Agent
     ↓
Risk Sentinel
     ↓
Execution Agent
     ↓
Portfolio Monitor
     ↓
Exit Agent
```

Each stage is implemented as a separate, testable module.

The complete orchestration is handled by:

```text
core/orchestration/pipeline.py
```

This allows the same architecture to be used for offline simulations, paper trading, testing, and future production integrations.

---

# 🏗️ System Architecture

```text
                         ┌─────────────────────┐
                         │     Market Data     │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │    Market Scout     │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │   Regime Analyst    │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │   Options Analyst   │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │   Strategy Agent    │
                         └──────────┬──────────┘
                                    ↓
                    ┌──────────────────────────────┐
                    │        RISK SENTINEL         │
                    │                              │
                    │  Deterministic Risk Engine  │
                    │  Independent Trade Veto     │
                    └──────────────┬───────────────┘
                                   ↓
                         ┌─────────────────────┐
                         │  Execution Agent    │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │ Portfolio Monitor   │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │     Exit Agent      │
                         └─────────────────────┘
```

### Design Principle

The strategy engine and risk engine are intentionally separated.

```text
Strategy Intelligence ≠ Execution Authority
```

A highly scored trade can still be rejected by the Risk Sentinel.

---

# 📈 Options Strategies

OptionSentinel currently supports four defined-risk strategies.

| Strategy                       | Eligible Regime                   | Risk Profile             |
| ------------------------------ | --------------------------------- | ------------------------ |
| **Bull Call Spread**           | BULLISH                           | Defined-risk debit       |
| **Bear Put Spread**            | BEARISH                           | Defined-risk debit       |
| **Iron Condor**                | RANGE + elevated IV               | Defined-risk credit      |
| **Long Volatility / Straddle** | HIGH_VOLATILITY + high confidence | Defined-risk entry debit |

## Strategy Selection

Strategies are **regime-aware**.

The system does not simply search for an options trade and execute it.

Instead:

```text
Market Conditions
       ↓
Regime Classification
       ↓
Eligible Strategies
       ↓
Candidate Generation
       ↓
Trade Scoring
       ↓
Risk Validation
       ↓
Execution
```

For example, the `long_volatility.py` strategy does not activate for every high-volatility signal.

It requires sufficiently high confidence and must still pass all Risk Sentinel checks.

---

# 🛡️ Risk Sentinel

The **Risk Sentinel** is the most important safety component in OptionSentinel.

Located in:

```text
risk/veto.py
```

it provides an independent, deterministic authorization layer between strategy generation and order execution.

### Risk Rules

`risk/limits.py` contains **13 independent deterministic risk rules**, covering areas such as:

* Buying-power validation
* Maximum trade risk
* Maximum portfolio risk
* Position concentration
* Drawdown protection
* Daily loss protection
* Liquidity checks
* Duplicate-order prevention
* Stale-market-data detection
* Contract sanity checks
* Position-size constraints
* Execution safety checks
* Account-level trading halts

The exact risk implementation is intentionally deterministic and does not depend on LLM output.

---

# ⚖️ Risk Verdicts

Every candidate trade must receive one of four verdicts:

### ✅ APPROVE

The trade passes all risk checks and can proceed at its calculated size.

### ⚠️ REDUCE_SIZE

The trade is acceptable, but the requested position size exceeds a safety constraint.

The Risk Sentinel calculates a smaller permissible quantity.

### ❌ REJECT

The trade is blocked.

The system records itemized reasons explaining exactly which risk rules failed.

### 🚨 EMERGENCY_HALT

An account-wide circuit breaker is triggered.

Examples include:

* Excessive drawdown
* Daily loss threshold breach
* Repeated rejected trades
* Other critical account-level conditions

Once triggered:

```text
NO NEW ENTRIES
```

regardless of trade quality.

---

# 🔐 Why the Risk Layer Matters

A central design goal of OptionSentinel is preventing an AI component from directly controlling execution.

For example:

```text
Trade Score = 98/100
        ↓
Risk Check
        ↓
Concentration Limit Exceeded
        ↓
REJECT
```

This means a high-confidence or high-scoring strategy **cannot bypass hardcoded safety constraints**.

### Core philosophy

> **AI proposes. Deterministic controls decide.**

---

# 🤖 Multi-Agent Architecture

OptionSentinel divides the trading workflow into specialized agents.

### Market Scout

Collects and normalizes market information.

### Regime Analyst

Determines whether the market is:

```text
BULLISH
BEARISH
RANGE
HIGH_VOLATILITY
```

using deterministic technical signals.

### Options Analyst

Evaluates available options contracts and relevant market characteristics.

### Strategy Agent

Generates candidate trades based on the current regime.

### Risk Sentinel

Independently validates every candidate.

### Execution Agent

Submits only trades that pass execution gating.

### Portfolio Monitor

Tracks open positions and portfolio state.

### Exit Agent

Determines when an existing position should be closed according to deterministic rules.

---

# 🧩 Broker Architecture

OptionSentinel uses a broker abstraction so that the trading logic does not depend directly on Alpaca.

The core interface is:

```text
core/interfaces/broker.py
```

which defines the `BrokerAdapter` protocol.

The rest of the system depends on this interface rather than Alpaca-specific implementation details.

### Implementations

#### Real Alpaca Adapter

```text
integrations/alpaca/adapter.py
```

Provides Alpaca paper/live REST integration through `alpaca-py`.

#### Mock Adapter

```text
integrations/alpaca/mock_adapter.py
```

Provides deterministic synthetic market and account data.

The mock adapter is used by:

* `DRY_RUN`
* Offline testing
* Simulation
* Unit tests
* CI workflows

This makes the core trading pipeline reproducible even without Alpaca credentials.

---

# 🔌 MCP & CLI Integration

## MCP

```text
integrations/alpaca_mcp/client.py
```

documents the integration seam for using OptionSentinel through an MCP-connected agent session.

The autonomous trading pipeline does **not** require MCP to operate.

## Alpaca CLI

```text
integrations/alpaca_cli/cli.py
```

detects and health-checks the Alpaca CLI when available.

The application does not require the CLI to be installed.

Running:

```bash
python -m scripts.health_check
```

reports the CLI state and continues gracefully if it is unavailable.

---

# ⚙️ Execution Modes

Execution behavior is controlled by:

```env
EXECUTION_MODE
```

| Mode                    | Adapter           | Submits Orders? |
| ----------------------- | ----------------- | --------------- |
| `DRY_RUN`               | Mock              | ❌ Never         |
| `PAPER_SIMULATION`      | Mock              | ❌ Never         |
| `PAPER_MANUAL_APPROVAL` | Real Alpaca Paper | ❌ Never         |
| `PAPER_AUTONOMOUS`      | Real Alpaca Paper | ✅ Yes           |
| `LIVE`                  | —                 | 🚫 Hard-blocked |

### DRY_RUN

Safe offline execution using deterministic mock data.

### PAPER_SIMULATION

Simulated paper environment without real broker submissions.

### PAPER_MANUAL_APPROVAL

Uses the real Alpaca paper environment to build and validate trades, but stops before order submission.

### PAPER_AUTONOMOUS

Allows approved trades to be submitted automatically to the Alpaca paper account.

Only:

```text
APPROVE
REDUCE_SIZE
```

verdicts are eligible for execution.

### LIVE

Live trading is intentionally hard-blocked.

The system cannot automatically escalate itself into live trading.

---

# 🔒 Credential & Execution Safety

`PAPER_MANUAL_APPROVAL` and `PAPER_AUTONOMOUS` require valid Alpaca credentials.

The application refuses to start these modes when credentials are missing or still contain placeholder values.

Example:

```env
APCA_API_KEY_ID=your_paper_key_id
APCA_API_SECRET_KEY=your_paper_secret_key

ALPACA_ENV=paper

EXECUTION_MODE=DRY_RUN

ALPACA_LIVE_TRADING_CONFIRMED=false
```

---

# 🧪 Testing

OptionSentinel is designed to be testable without access to a real brokerage account.

### Install development dependencies

```bash
make dev-install
```

### Run the complete test suite

```bash
make test
```

### Unit tests

```bash
make test-unit
```

Covers:

* Regime classification
* Trade scoring
* Risk rules
* Strategy eligibility
* Position sizing
* Failure modes
* Safety controls

### Full offline simulation

```bash
make test-sim
```

### Integration tests

```bash
make test-integration
```

Integration tests require real Alpaca paper credentials and automatically skip when they are unavailable.

---

# ✅ Current Test Status

The current offline suite contains:

```text
106 tests passed
1 test skipped
1 deprecation warning
```

The skipped test requires explicit order-submission opt-in.

A dedicated risk regression test also demonstrates that:

> A high-scoring trade can still be rejected because of portfolio concentration risk.

This validates the separation between **trade quality** and **risk authorization**.

---

# 🚀 Getting Started

## 1. Clone the repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd optionsentinel
```

## 2. Create a virtual environment

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
```

## 3. Install dependencies

```bash
pip install -e ".[dev]"
```

## 4. Configure environment variables

Copy the example environment file:

```bash
cp .env.example .env
```

Then configure:

```env
APCA_API_KEY_ID=your_paper_key_id
APCA_API_SECRET_KEY=your_paper_secret_key

ALPACA_ENV=paper

EXECUTION_MODE=DRY_RUN

ALPACA_LIVE_TRADING_CONFIRMED=false
```

### Optional LLM Explanation Layer

```env
FEATHERLESS_API_KEY=your_featherless_key
FEATHERLESS_BASE_URL=https://api.featherless.ai/v1
FEATHERLESS_MODEL=meta-llama/Meta-Llama-3-70B-Instruct
```

The LLM is optional and is used for explanation/narration rather than core trading decisions.

---

# 🩺 Health Check

Run:

```bash
python -m scripts.health_check
```

The health check validates the configured environment and reports integration status.

Without credentials, OptionSentinel automatically falls back to the mock broker where supported.

---

# ▶️ Run the Autonomous Pipeline

Start a dry run with:

```bash
python -m core.orchestration.pipeline
```

Recommended first execution mode:

```env
EXECUTION_MODE=DRY_RUN
```

This allows the complete pipeline to be evaluated without submitting orders.

---

# 🎬 Hackathon Demo Flow

A typical **3–5 minute demonstration** can follow this sequence:

### 1. Health Check

```bash
python -m scripts.health_check
```

Demonstrate the broker/integration status.

### 2. Run the Pipeline

```bash
python -m core.orchestration.pipeline
```

Show the progression:

```text
Market Scout
→ Regime Analyst
→ Options Analyst
→ Strategy Agent
→ Risk Sentinel
→ Execution
```

### 3. Show Risk Decisions

Display at least:

```text
APPROVE
```

and:

```text
REJECT
```

or:

```text
REDUCE_SIZE
```

from the trade journal.

### 4. Demonstrate Execution

For a controlled paper-trading demonstration, place a small test order and verify the resulting position state.

```bash
python check_positions.py
```

### 5. Show Performance Results

Open:

```text
reports/performance.md
```

Synthetic/backtest results should remain clearly labeled as simulated results.

---

# 📁 Project Structure

```text
optionsentinel/
│
├── agents/
│   ├── market_scout.py
│   ├── regime_analyst.py
│   ├── options_analyst.py
│   ├── strategy_agent.py
│   ├── execution_agent.py
│   ├── portfolio_monitor.py
│   └── exit_agent.py
│
├── strategies/
│   ├── bull_call_spread.py
│   ├── bear_put_spread.py
│   ├── iron_condor.py
│   └── long_volatility.py
│
├── risk/
│   ├── limits.py
│   └── veto.py
│
├── core/
│   ├── interfaces/
│   │   └── broker.py
│   └── orchestration/
│       └── pipeline.py
│
├── integrations/
│   ├── alpaca/
│   │   ├── adapter.py
│   │   └── mock_adapter.py
│   │
│   ├── alpaca_mcp/
│   │   └── client.py
│   │
│   └── alpaca_cli/
│       └── cli.py
│
├── tests/
│   └── unit/
│       └── test_risk.py
│
├── reports/
│   └── performance.md
│
├── scripts/
│   └── health_check.py
│
├── check_positions.py
├── .env.example
├── pyproject.toml
├── Makefile
└── README.md
```

---

# 📊 Design Philosophy

OptionSentinel is built around five principles:

### 1. Deterministic over opaque

Critical trading decisions are reproducible and auditable.

### 2. Risk before execution

No strategy can bypass the Risk Sentinel.

### 3. Defined-risk strategies

The system focuses on options structures with explicitly constrained downside.

### 4. Broker independence

Trading logic communicates through a broker abstraction rather than Alpaca-specific code.

### 5. Safe-by-default execution

The default mode is:

```text
DRY_RUN
```

and live trading is hard-blocked.

---

# ⚠️ Known Limitations

OptionSentinel is a hackathon project and is not presented as a production-ready financial system.

Current limitations include:

* Real Alpaca option-chain retrieval is implemented but should be validated against live paper responses before relying on complex multi-leg construction.
* Multi-leg options order submission may require additional validation with Alpaca paper-trading responses.
* There is currently no frontend dashboard.
* FastAPI endpoints exist, but the persistence layer is not fully wired into the live pipeline.
* News/catalyst scoring is currently a placeholder.
* `probability_estimate` is currently `None`.
* Backtest/performance data should be interpreted as synthetic unless explicitly identified otherwise.

---

# ⚠️ Disclaimer

OptionSentinel is an experimental software project created for the **Alpaca AI Trading Agents Hackathon**.

It is **not financial advice**, and it should not be interpreted as a recommendation to buy or sell securities or options.

Options trading involves substantial risk and may result in significant losses.

---

# 👥 Team Scorpion

### 🦂 Team Scorpion

**Awais Jabbar**
Backend · UI/UX · DevOps · Team Captain

**Muhammad Ekremah**
AI/ML · API Integration

**Alveena Haneef**
Team Member

---

# 🏆 Built for the Alpaca AI Trading Agents Hackathon

**Project:** OptionSentinel
**Team:** Team Scorpion
**Platform:** Alpaca Trading API
**Architecture:** Multi-Agent + Deterministic Risk Engine
**Primary Environment:** Paper Trading / Dry Run

> **AI proposes. Risk Sentinel decides.**

---

# 📄 License

This project is licensed under the **MIT License**.

See [`LICENSE`](LICENSE) for details.
