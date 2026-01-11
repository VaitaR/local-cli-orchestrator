.PHONY: fmt lint test test-integration smoke-llm install clean help

# Default target
help:
	@echo "orx - Local CLI Agent Orchestrator"
	@echo ""
	@echo "Usage:"
	@echo "  make install          Install package in development mode"
	@echo "  make fmt              Format code with ruff"
	@echo "  make lint             Lint code with ruff and mypy"
	@echo "  make test             Run unit tests"
	@echo "  make test-integration Run integration tests"
	@echo "  make smoke-llm        Run LLM smoke tests (requires RUN_LLM_TESTS=1)"
	@echo "  make clean            Remove build artifacts"

install:
	python -m pip install -e ".[dev,dashboard]"

run:
	python -m orx.dashboard

fmt:
	python -m ruff format .

lint:
	python -m ruff check .
	python -m ruff check --fix .
	python -m mypy src/orx tests

test:
	python -m pytest tests/unit -q

test-integration:
	python -m pytest tests/integration -q

smoke-llm:
	@if [ "$$RUN_LLM_TESTS" = "1" ]; then \
		python -m pytest tests/smoke -q; \
	else \
		echo "Skipping LLM smoke tests. Set RUN_LLM_TESTS=1 to run."; \
	fi

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

kill:
	pkill -f "python -m orx.dashboard" || true
