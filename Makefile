.PHONY: check-python fmt lint test test-integration smoke-llm install clean help run kill

PYTHON ?= python3.11

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

check-python:
	@$(PYTHON) -c "import sys; v=sys.version_info[:2]; \
assert (3, 11) <= v < (3, 13), \
'Unsupported Python version {}.{}. Use Python 3.11 or 3.12.'.format(*v)"

install: check-python
	$(PYTHON) -m pip install -e ".[dev,dashboard]"

# http://127.0.0.1:8421
run: check-python
	$(PYTHON) -m orx.dashboard

fmt: check-python
	$(PYTHON) -m ruff format .

lint: check-python
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m mypy src/orx tests

test: check-python
	$(PYTHON) -m pytest tests/unit -q

test-integration: check-python
	$(PYTHON) -m pytest tests/integration -q

smoke-llm: check-python
	@if [ "$$RUN_LLM_TESTS" = "1" ]; then \
		$(PYTHON) -m pytest tests/smoke -q; \
	else \
		echo "Skipping LLM smoke tests. Set RUN_LLM_TESTS=1 to run."; \
	fi

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

kill:
	pkill -f "python -m orx.dashboard" || true
