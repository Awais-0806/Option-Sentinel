FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY core ./core
COPY agents ./agents
COPY strategies ./strategies
COPY risk ./risk
COPY integrations ./integrations
COPY data ./data
COPY apps ./apps
COPY backtest ./backtest
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
