#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"

SKIP_DB_CHECK=0
for arg in "$@"; do
  case "$arg" in
    --offline|--skip-db-check)
      SKIP_DB_CHECK=1
      ;;
    --help|-h)
      echo "Usage: ./scripts/check.sh [--skip-db-check]"
      echo "Unit tests still require local PostgreSQL; no cloud calls are made."
      exit 0
      ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

echo "===================================================="
echo "           Signal Slate - Verification Suite         "
echo "===================================================="

echo ""
echo "--> [1/8] Checking Python formatting (ruff)..."
uv run --locked --extra dev ruff format --check .

echo ""
echo "--> [2/8] Linting Python code (ruff)..."
uv run --locked --extra dev ruff check .

echo ""
echo "--> [3/8] Type-checking Python code (mypy)..."
uv run --locked --extra dev mypy services/api tests

echo ""
echo "--> [4/8] Running Python unit tests (pytest - includes local PostgreSQL)..."
uv run --locked --extra dev pytest tests/unit tests/evaluation tests/security

echo ""
echo "--> [5/8] Linting Frontend code (eslint)..."
npm run lint

echo ""
echo "--> [6/8] Type-checking Frontend code (tsc)..."
npm run typecheck

echo ""
echo "--> [7/8] Running Frontend unit tests (vitest)..."
npm run test

echo ""
echo "--> [8/8] Building Frontend production assets (vite)..."
npm run build

uv run --locked --extra dev python scripts/export-contracts.py --check
npm run contracts:check
./scripts/check-privacy.sh

echo ""
if [ "$SKIP_DB_CHECK" -eq 1 ]; then
  echo "--> [DB] Skipping standalone database check; database-backed unit tests still ran."
else
  echo "--> [DB] Running explicit database connection check..."
  uv run --locked --extra dev python -m signal_slate.db_check
fi

echo ""
echo "===================================================="
echo "  [PASS] All Signal Slate verification checks passed! "
echo "===================================================="
