.PHONY: install dev-install health test test-unit test-integration test-sim test-backtest lint format run docker-build docker-up

install:
	pip install -e . --break-system-packages

dev-install:
	pip install -e ".[dev]" --break-system-packages

health:
	python -m scripts.health_check

test:
	pytest -v

test-unit:
	pytest tests/unit -v

test-integration:
	pytest tests/integration -v

test-sim:
	pytest tests/simulation -v

test-backtest:
	pytest tests/backtest -v

lint:
	ruff check .
	black --check .

format:
	ruff check --fix .
	black .

run:
	uvicorn apps.api.main:app --reload --port 8000

docker-build:
	docker build -f docker/Dockerfile -t optionsentinel:latest .

docker-up:
	docker compose -f docker-compose.yml up --build
