"""
Minimal FastAPI surface. This is the backend a dashboard frontend would
call — it does not itself render anything. Endpoints are deliberately
thin: they call into core/orchestration/pipeline.py and integrations/,
never duplicate logic.

Run: uvicorn apps.api.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from core.config.settings import get_settings

app = FastAPI(title="OptionSentinel API", version="0.1.0")


def _get_broker():
    settings = get_settings()
    if settings.alpaca_api_key and settings.alpaca_secret_key:
        try:
            from integrations.alpaca.adapter import AlpacaBrokerAdapter
            return AlpacaBrokerAdapter(settings)
        except Exception:
            pass
    from integrations.alpaca.mock_adapter import MockBrokerAdapter
    return MockBrokerAdapter(settings)


@app.get("/health")
def health():
    from integrations.alpaca_cli.cli import cli_health_check

    settings = get_settings()
    broker = _get_broker()
    return {
        "broker": broker.health_check(),
        "cli": cli_health_check(),
        "execution_mode": settings.execution_mode.value,
        "deploy_stage": settings.deploy_stage.value,
    }


@app.get("/account")
def account():
    broker = _get_broker()
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

    settings = get_settings()
    broker = _get_broker()
    result = run_pipeline(settings, broker, symbols=payload.symbols)
    return result.summary()
