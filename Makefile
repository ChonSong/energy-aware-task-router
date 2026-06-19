.PHONY: dev test build deploy clean lint format type-check security-scan pre-commit install-dev

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

type-check:
	mypy energy_router/

security-scan:
	bandit -c pyproject.toml -r energy_router/

pre-commit:
	pre-commit run --all-files

install-dev:
	pip install -e ".[dev]"
	pre-commit install || true

deploy-systemd:
	@echo "==> Installing systemd service... (requires sudo)"
	sudo cp deploy/energy-router.service /etc/systemd/system/energy-router.service
	sudo systemctl daemon-reload
	sudo systemctl enable energy-router
	sudo systemctl restart energy-router || sudo systemctl start energy-router
	@echo "==> Service status:"
	sudo systemctl status energy-router --no-pager

deploy-tunnel:
	@echo "==> Running Cloudflare Tunnel..."
	cloudflared tunnel --config deploy/cloudflared/config.yaml run

deploy-all: deploy
	$(MAKE) deploy-systemd

.PHONY: deploy-systemd deploy-tunnel
