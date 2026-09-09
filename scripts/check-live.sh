#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == "--help" ]]; then
  echo 'Usage: ./scripts/check-live.sh --cases /private/cases.json --output /private/report.json'
  echo 'Or: ./scripts/check-live.sh --workflow --preset a --runs 3 --output /private/report.json'
  echo 'Runs at most 18 Gemini requests across at most 9 normal daily-budgeted sessions.'
  echo 'Requires local database, Vertex ADC, enabled runtime and private reviewed input set.'
  exit 0
fi
if [[ "${LIVE_TESTS_ENABLED:-}" != "true" ]]; then
  echo 'BLOCKED: set LIVE_TESTS_ENABLED=true to explicitly permit bounded cloud evaluation.' >&2
  exit 2
fi
if [[ "${SIGNAL_SLATE_RUNTIME_ENABLED:-true}" != "true" ]]; then
  echo 'BLOCKED: live runtime is disabled.' >&2
  exit 2
fi
if [[ "${1:-}" == "--workflow" ]]; then
  shift
  uv run --locked --extra dev python scripts/run-live-workflow.py "$@"
else
  uv run --locked --extra dev python tests/evaluation/run_live_constraints.py "$@"
fi
