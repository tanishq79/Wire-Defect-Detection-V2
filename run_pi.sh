#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${SURFACEAI_PORT:-8000}"

if [ -z "${VIRTUAL_ENV:-}" ]; then
  echo "Virtual environment is not active."
  echo "Run: source .venv/bin/activate"
  exit 1
fi

python -m py_compile app.py
echo "Using the installed project version (automatic Git updates disabled)."
echo "Starting SurfaceAI on http://127.0.0.1:${PORT}"
echo "Use Ctrl+C to stop."
uvicorn app:app --host 0.0.0.0 --port "$PORT" --no-access-log
