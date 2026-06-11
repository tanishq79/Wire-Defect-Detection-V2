#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -z "${VIRTUAL_ENV:-}" ]; then
  echo "Virtual environment is not active."
  echo "Run: source .venv/bin/activate"
  exit 1
fi

python -m py_compile app.py
echo "Starting SurfaceAI on http://127.0.0.1:8000"
echo "Use Ctrl+C to stop."
uvicorn app:app --host 0.0.0.0 --port 8000
