#!/usr/bin/env bash
# Start the local API and Vite together. Credentials remain on the server.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

case "${1:-}" in
  "") export SIGNAL_SLATE_RUNTIME_ENABLED=false ;;
  --live) export SIGNAL_SLATE_RUNTIME_ENABLED=true ;;
  --help|-h)
    echo "Usage: ./scripts/dev.sh [--live]"
    echo "Default: local preview; --live permits Gemini and Grafana requests."
    exit 0 ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo "Expected at most one option." >&2
  exit 2
fi

for program in uv npm; do
  command -v "$program" >/dev/null || { echo "Missing prerequisite: $program" >&2; exit 1; }
done

uv run --locked --extra dev python -m signal_slate.db_check
uv run --locked --extra dev alembic upgrade head

# Separate process groups let cleanup stop npm's Vite child as well as its parent.
set -m
API_PID=""
WEB_PID=""
cleanup() {
  trap - EXIT INT TERM
  if [ -n "$API_PID" ]; then kill -- "-$API_PID" 2>/dev/null || true; fi
  if [ -n "$WEB_PID" ]; then kill -- "-$WEB_PID" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

uv run --locked --extra dev uvicorn signal_slate.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
npm --prefix apps/web run dev -- --host localhost --port 5173 --strictPort &
WEB_PID=$!
echo "Open http://localhost:5173 — Ctrl+C stops both servers."
echo "Cloud runtime enabled: $SIGNAL_SLATE_RUNTIME_ENABLED"
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done
echo "A development server stopped; shutting down the other." >&2
exit 1
