.DEFAULT_GOAL := help

# --- Project Settings ---
PROJECT_NAME := opentelemetry-instrumentation-claude-agent-sdk
SRC_DIR := src
TEST_DIR := tests
MIN_COVERAGE := 80
PYTHON_VERSION := 3.10

# --- Colors ---
BLUE := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

# ============================================================================
# HELP
# ============================================================================

.PHONY: help
help: ## Show this help message
	@echo "$(BLUE)$(PROJECT_NAME)$(RESET) - Development Commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'

# ============================================================================
# PREREQUISITES
# ============================================================================

.PHONY: check-python check-uv
check-python: ## Check Python is installed
	@python3 --version > /dev/null 2>&1 || (echo "$(RED)Python 3 not found$(RESET)" && exit 1)

check-uv: ## Check uv is installed
	@uv --version > /dev/null 2>&1 || (echo "$(RED)uv not found. Install: https://docs.astral.sh/uv/$(RESET)" && exit 1)

# ============================================================================
# SETUP
# ============================================================================

.PHONY: init install install-dev install-prod install-hooks update-deps
init: check-uv install-dev install-hooks ## Full project initialization

install: check-uv ## Install project (default extras)
	uv sync

install-dev: check-uv ## Install with dev dependencies
	uv sync --all-extras

install-prod: check-uv ## Install production dependencies only
	uv sync --no-dev

install-hooks: ## Install pre-commit hooks
	uv run pre-commit install

update-deps: check-uv ## Update all dependencies
	uv lock --upgrade
	uv sync --all-extras

# ============================================================================
# TESTING
# ============================================================================

.PHONY: test test-unit test-integration test-coverage test-failed test-parallel
test: ## Run all tests
	uv run pytest $(TEST_DIR)

test-unit: ## Run unit tests only
	uv run pytest $(TEST_DIR)/unit

test-integration: ## Run integration tests only
	uv run pytest $(TEST_DIR)/integration -m integration || test $$? -eq 5

test-coverage: ## Run tests with coverage report
	uv run pytest $(TEST_DIR) --cov --cov-report=term-missing --cov-report=xml:coverage.xml --cov-fail-under=$(MIN_COVERAGE)

test-failed: ## Re-run only failed tests
	uv run pytest $(TEST_DIR) --lf

test-parallel: ## Run tests in parallel
	uv run pytest $(TEST_DIR) -n auto

# ============================================================================
# CODE QUALITY
# ============================================================================

.PHONY: lint lint-fix format format-check type-check security pre-commit
lint: ## Run linter (ruff)
	uv run ruff check $(SRC_DIR) $(TEST_DIR)

lint-fix: ## Run linter with auto-fix
	uv run ruff check --fix $(SRC_DIR) $(TEST_DIR)

format: ## Format code (black + ruff)
	uv run black $(SRC_DIR) $(TEST_DIR)
	uv run ruff check --fix --select I $(SRC_DIR) $(TEST_DIR)

format-check: ## Check code formatting
	uv run black --check $(SRC_DIR) $(TEST_DIR)

type-check: ## Run type checker (mypy)
	uv run mypy $(SRC_DIR)

security: ## Run security checks (bandit + pip-audit)
	uv run bandit -r $(SRC_DIR) -c pyproject.toml
	uv run pip-audit --progress-spinner=off

pre-commit: ## Run all pre-commit hooks
	uv run pre-commit run --all-files

# ============================================================================
# CI
# ============================================================================

.PHONY: ci ci-github ci-fast
ci: lint format-check type-check security test-coverage ## Full CI pipeline (local)

ci-github: pre-commit test-coverage security ## CI pipeline (GitHub Actions)

ci-fast: lint test ## Fast CI check (lint + test only)

# ============================================================================
# BUILD
# ============================================================================

.PHONY: build build-check clean clean-all
build: check-uv ## Build distribution packages
	uv build

build-check: build ## Build and check distribution
	uv run python -m tarfile -l dist/*.tar.gz

clean: ## Clean build artifacts
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -f coverage.xml .coverage

clean-all: clean ## Clean everything including venv
	rm -rf .venv
