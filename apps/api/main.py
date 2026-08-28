"""
Minimal FastAPI surface. This is the backend a dashboard frontend would
call — it does not itself render anything. Endpoints are deliberately
thin: they call into core/orchestration/pipeline.py and integrations/,
never duplicate logic.

Run: uvicorn apps.api.main:app --reload

Day-1 fix: adapter selection now goes through
integrations/broker_factory.py::get_broker_adapter, which is keyed
strictly on Settings.execution_mode. Previously this file picked the
real Alpaca adapter whenever credential *strings* were non-empty —
including the placeholder strings shipped in .env.example — which made
DRY_RUN attempt real (failing) Alpaca API calls and return HTTP 500.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.config.settings import get_settings
from integrations.alpaca.adapter import LiveTradingDisabledError
from integrations.broker_factory import BrokerConfigurationError, get_broker_adapter

app = FastAPI(title="OptionSentinel API", version="0.1.0")

MOCK_MODES = ("DRY_RUN", "PAPER_SIMULATION")


def _resolve_broker():
    """Wraps get_broker_adapter with clean HTTP error semantics.
    A misconfigured mode (e.g. PAPER_MANUAL_APPROVAL with no credentials)
    is a client/config problem — surfaced as 400, not a 500 crash."""
    settings = get_settings()
    try:
        return get_broker_adapter(settings), settings
    except (BrokerConfigurationError, LiveTradingDisabledError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/health")
def health():
    from integrations.alpaca_cli.cli import cli_health_check

    broker, settings = _resolve_broker()
    return {
        "broker": broker.health_check(),
        "cli": cli_health_check(),
        "execution_mode": settings.execution_mode.value,
        "deploy_stage": settings.deploy_stage.value,
        "data_source": "MOCK" if settings.execution_mode.value in MOCK_MODES else "REAL_ALPACA_PAPER",
    }


@app.get("/account")
def account():
    broker, _ = _resolve_broker()
    snapshot = broker.get_account()
    return {
        "equity": snapshot.equity,
        "buying_power": snapshot.buying_power,
        "cash": snapshot.cash,
        "daily_pnl": snapshot.daily_pnl,
        "peak_equity": snapshot.peak_equity,
        "is_paper": snapshot.is_paper,
    }


class RunPipelineRequest(BaseModel):
    symbols: list[str] | None = None


@app.post("/pipeline/run")
def run_pipeline_endpoint(payload: RunPipelineRequest):
    from core.orchestration.pipeline import run_pipeline

    broker, settings = _resolve_broker()
    result = run_pipeline(settings, broker, symbols=payload.symbols)
    summary = result.summary()
    summary["data_source"] = "MOCK" if settings.execution_mode.value in MOCK_MODES else "REAL_ALPACA_PAPER"
    summary["execution_mode"] = settings.execution_mode.value
    return summary
