#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${SURFACEAI_APP_DIR:-$HOME/Desktop/Wire-Defect-Detection-V2}"
BRANCH="${SURFACEAI_BRANCH:-codex/pi-ui-api-hardening}"
URL="http://127.0.0.1:8000"

cd "$APP_DIR"

echo "SurfaceAI starting..."
echo "Project: $APP_DIR"
echo "Branch:  $BRANCH"

if command -v git >/dev/null 2>&1; then
  echo "Checking for updates..."
  git fetch origin
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Virtual environment not found at .venv"
  echo "Please run the first-time installation commands before using the launcher."
  read -r -p "Press Enter to close..."
  exit 1
fi

".venv/bin/python" -m py_compile app.py

if pgrep -f "uvicorn app:app.*--port 8000" >/dev/null 2>&1; then
  echo "Server is already running."
else
  echo "Starting server..."
  ".venv/bin/python" -m uvicorn app:app --host 0.0.0.0 --port 8000 &
fi

echo "Waiting for web app..."
for _ in $(seq 1 30); do
  if curl -fsS "$URL/status" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "Opening $URL"
if command -v chromium-browser >/dev/null 2>&1; then
  chromium-browser "$URL" >/dev/null 2>&1 &
elif command -v chromium >/dev/null 2>&1; then
  chromium "$URL" >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
else
  echo "Open this URL manually: $URL"
fi

echo "SurfaceAI is running. Keep this window open while using the app."
echo "Press Ctrl+C here only when you want to stop the server."
wait
