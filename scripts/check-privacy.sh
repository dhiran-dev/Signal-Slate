#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Run npm run build first. No cloud traffic or secret values are printed.
uv run --locked --extra dev pytest tests/security/test_leak_check.py -q
