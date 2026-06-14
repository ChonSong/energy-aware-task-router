.PHONY: dev test build deploy clean

dev:
	uvicorn energy_router.api:app --host 0.0.0.0 --port 8009 --reload

test:
	pytest tests/ -v

test-coverage:
	pytest tests/ -v --cov=energy_router --cov-report=term-missing

build:
	docker compose build

deploy:
	docker compose up -d

clean:
	rm -rf __pycache__ energy_router/__pycache__ tests/__pycache__
	rm -rf .pytest_cache
	rm -rf *.egg-info
	rm -f routing_audit.db
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

lint:
	ruff check energy_router/ tests/

format:
	ruff format energy_router/ tests/
