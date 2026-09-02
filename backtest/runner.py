"""
Backtest runner (Phase G/H).

Design invariant carried over from the live pipeline, stated explicitly
per requirement #14: this runner calls risk.veto.RiskSentinel DIRECTLY —
the exact same class core/orchestration/pipeline.py uses. There is no
separate, parallel, backtest-only risk engine that could silently drift
from what the live/paper system would actually do.

Exit model (disclosed, applies to every strategy — bull call, bear put,
iron condor, long vol — identically, since P&L is computed leg-by-leg,
not strategy-specifically): HOLD TO EXPIRATION. No early-exit rule is
implemented (the Exit Agent described in docs/ARCHITECTURE.md does not
exist yet for the backtest). This is a real simplification — a live
system might close winners/losers early — and is reported as a Known
Limitation, not hidden.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from backtest.data_capability import Evaluability, gate_dataset_for_backtest
from backtest.data_schema import HistoricalDataset
from backtest.exit_engine import ExitConfig, ExitRuleType, check_early_exit
from backtest.pnl import COST_BASE, CostAssumptions, TradeExecution, close_position_early, entry_to_expiration_pnl
from backtest.replay_engine import decide_at
from core.config.settings import Settings
from core.models.risk import RiskVerdict
from core.models.trade import SizeTier
from risk.limits import OpenPosition, PortfolioState


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    name: str
    forced_strategy: object = None  # a strategies.base.Strategy instance, for baselines 1-3
    skip_contract_validation: bool = False  # baseline 4 ("simple regime-only selector")
    cost: CostAssumptions = COST_BASE
    starting_equity: float = 100_000.0
    warmup_days: int = 55  # must exceed RegimeClassifier's slow trend window
    exit_config: ExitConfig = None  # None -> defaults to hold-to-expiration

    def __post_init__(self):
        if self.exit_config is None:
            object.__setattr__(self, "exit_config", ExitConfig())


@dataclass
class BacktestResult:
    config_name: str
    dataset_label: str
    data_capability_status: str
    data_capability_reasons: tuple[str, ...]
    trades: list[TradeExecution] = field(default_factory=list)
    still_open_at_end: int = 0
    signals: int = 0
    no_trade_outcomes: int = 0
    risk_rejected: int = 0
    risk_reduced: int = 0
    risk_approved: int = 0
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    early_exits: int = 0

    def stats(self) -> dict:
        if not self.trades:
            return {
                "trade_count": 0, "note": "zero completed trades — all other stats are undefined, not zero",
            }
        pnls = sorted(t.net_pnl for t in self.trades)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        equity_values = [e for _, e in self.equity_curve] or [0.0]
        peak = equity_values[0]
        max_dd = 0.0
        for e in equity_values:
            peak = max(peak, e)
            if peak > 0:
                max_dd = max(max_dd, (peak - e) / peak)

        n = len(pnls)
        median_pnl = pnls[n // 2] if n % 2 else (pnls[n // 2 - 1] + pnls[n // 2]) / 2

        return {
            "trade_count": n,
            "win_rate": round(len(wins) / n, 4),
            "avg_pnl": round(sum(pnls) / n, 2),
            "median_pnl": round(median_pnl, 2),
            "total_pnl": round(sum(pnls), 2),
            "max_drawdown_pct": round(max_dd, 4),
            "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
            "avg_winner": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loser": round(sum(losses) / len(losses), 2) if losses else None,
            "still_open_at_end": self.still_open_at_end,
            "signals": self.signals,
            "no_trade_outcomes": self.no_trade_outcomes,
            "risk_rejected": self.risk_rejected,
            "risk_reduced": self.risk_reduced,
            "risk_approved": self.risk_approved,
            "no_trade_rate": round(self.no_trade_outcomes / self.signals, 4) if self.signals else None,
            "rejection_rate": round(self.risk_rejected / self.signals, 4) if self.signals else None,
            "early_exits": self.early_exits,
            "sample_size_warning": (
                f"only {n} completed trades — below the 10-trade floor for treating this as "
                "evidence of a robust edge in either direction" if n < 10 else None
            ),
        }


def run_backtest(dataset: HistoricalDataset, settings: Settings, config: BacktestConfig) -> BacktestResult:
    capability = gate_dataset_for_backtest(dataset)
    result = BacktestResult(
        config_name=config.name, dataset_label=dataset.label(),
        data_capability_status=capability.status.value, data_capability_reasons=capability.reasons,
    )
    if capability.status == Evaluability.NOT_EVALUATABLE:
        return result  # zero trades, reason recorded — never silently proceeds

    equity = config.starting_equity
    peak_equity = config.starting_equity
    open_positions: list[dict] = []
    closes_by_date = {d.as_of_date: d.underlying_close for d in dataset.days}
    all_dates = [d.as_of_date for d in dataset.days]

    for i, as_of in enumerate(all_dates):
        if i < config.warmup_days:
            continue

        still_open = []
        for pos in open_positions:
            should_exit_early, exit_reason = False, None
            if config.exit_config.rule != ExitRuleType.EXPIRATION and pos["expiration"] > as_of:
                should_exit_early, exit_reason = check_early_exit(
                    pos["candidate"], dataset, as_of, pos["entry_date"], config.exit_config
                )

            if should_exit_early:
                from backtest.exit_engine import reprice_position
                mtm_pnl_per_contract = reprice_position(pos["candidate"], dataset, as_of)
                # mtm_pnl_per_contract is P&L vs entry; reconstruct the exit NET VALUE
                # (entry_net + pnl/100) so close_position_early's accounting matches
                # entry_to_expiration_pnl's convention exactly.
                from backtest.pnl import _leg_entry_price
                entry_net = sum(
                    (_leg_entry_price(leg, config.cost) if leg.side == "BUY" else -_leg_entry_price(leg, config.cost))
                    for leg in pos["candidate"].legs
                )
                exit_net_value = entry_net + (mtm_pnl_per_contract / 100.0)
                execution = close_position_early(
                    pos["candidate"], pos["entry_date"], as_of, exit_net_value, quantity=pos["qty"], cost=config.cost
                )
                equity += execution.net_pnl
                peak_equity = max(peak_equity, equity)
                result.trades.append(execution)
                result.early_exits += 1
                continue

            if pos["expiration"] <= as_of:
                exit_underlying = closes_by_date.get(pos["expiration"], closes_by_date[as_of])
                execution = entry_to_expiration_pnl(
                    pos["candidate"], pos["entry_date"], exit_underlying, quantity=pos["qty"], cost=config.cost
                )
                equity += execution.net_pnl
                peak_equity = max(peak_equity, equity)
                result.trades.append(execution)
            else:
                still_open.append(pos)
        open_positions = still_open
        result.equity_curve.append((as_of, equity))

        portfolio = PortfolioState(
            equity=equity, buying_power=equity * 2, daily_pnl=0.0, peak_equity=peak_equity,
            open_positions=tuple(
                OpenPosition(trade_id=p["candidate"].trade_id, symbol=p["candidate"].symbol,
                             strategy=p["candidate"].strategy.value, risk_capital=p["candidate"].max_loss * p["qty"],
                             opened_at=datetime.combine(p["entry_date"], datetime.min.time())) for p in open_positions
            ),
        )

        decision = decide_at(
            dataset, as_of, portfolio, settings,
            skip_contract_validation=config.skip_contract_validation,
            forced_strategy=config.forced_strategy,
        )
        if decision.candidate is None:
            continue
        result.signals += 1

        if decision.candidate.size_tier == SizeTier.NO_TRADE or decision.risk_decision is None:
            result.no_trade_outcomes += 1
            continue

        verdict = decision.risk_decision.verdict
        if verdict == RiskVerdict.REJECT or verdict == RiskVerdict.EMERGENCY_HALT:
            result.risk_rejected += 1
            continue
        if verdict == RiskVerdict.REDUCE_SIZE:
            result.risk_reduced += 1
        else:
            result.risk_approved += 1

        qty = decision.risk_decision.approved_quantity or 1
        expiration = decision.candidate.legs[0].contract.expiration if decision.candidate.legs else as_of
        open_positions.append({"candidate": decision.candidate, "entry_date": as_of, "expiration": expiration, "qty": qty})

    result.still_open_at_end = len(open_positions)
    return result
