#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

BRANCH="${SURFACEAI_BRANCH:-codex/pi-ui-api-hardening}"

if [ -z "${VIRTUAL_ENV:-}" ]; then
  echo "Virtual environment is not active."
  echo "Run: source .venv/bin/activate"
  exit 1
fi

if command -v git >/dev/null 2>&1; then
  echo "Checking for updates..."
  git fetch origin
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
fi

python -m py_compile app.py
echo "Starting SurfaceAI on http://127.0.0.1:8000"
echo "Use Ctrl+C to stop."
uvicorn app:app --host 0.0.0.0 --port 8000
