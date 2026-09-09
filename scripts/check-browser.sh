#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! curl --fail --silent "${BROWSER_BASE_URL:-http://localhost:5173}/" >/dev/null; then
  echo 'Start the local API and web app with ./scripts/dev.sh before running browser checks.' >&2
  exit 1
fi
exec ./node_modules/.bin/playwright test "$@"
