#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${SURFACEAI_APP_DIR:-$HOME/Desktop/Wire-Defect-Detection-V2}"
BRANCH="${SURFACEAI_BRANCH:-main}"
URL="http://127.0.0.1:8000"
KIOSK_MODE="${SURFACEAI_KIOSK:-0}"

on_error() {
  local code=$?
  echo
  echo "SurfaceAI could not start. The command above failed with exit code $code."
  echo "Check the message above, then press Enter to close this window."
  read -r
  exit "$code"
}

trap on_error ERR

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
CHROMIUM_FLAGS=("$URL" "--no-first-run" "--disable-session-crashed-bubble")
if [ "$KIOSK_MODE" = "1" ]; then
  CHROMIUM_FLAGS+=("--kiosk" "--start-fullscreen")
fi

if command -v chromium-browser >/dev/null 2>&1; then
  chromium-browser "${CHROMIUM_FLAGS[@]}" >/dev/null 2>&1 &
elif command -v chromium >/dev/null 2>&1; then
  chromium "${CHROMIUM_FLAGS[@]}" >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
else
  echo "Open this URL manually: $URL"
fi

echo "SurfaceAI is running. Keep this window open while using the app."
if [ "$KIOSK_MODE" = "1" ]; then
  echo "Kiosk mode is enabled. Press Alt+F4 to leave Chromium."
fi
echo "Press Ctrl+C here only when you want to stop the server."
wait
