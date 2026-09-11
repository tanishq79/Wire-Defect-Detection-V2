#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${SURFACEAI_APP_DIR:-$HOME/Desktop/Wire-Defect-Detection-V2}"
BRANCH="${SURFACEAI_BRANCH:-main}"
PORT="${SURFACEAI_PORT:-8000}"
URL="http://127.0.0.1:${PORT}"
KIOSK_MODE="${SURFACEAI_KIOSK:-0}"
UPDATE_ON_START="${SURFACEAI_UPDATE_ON_START:-0}"
SERVER_PID=""
BROWSER_PID=""

# Enable the installed physical machine counter buttons by default. These can
# still be overridden for a Pi that uses GPIO14/GPIO15 for UART or other hardware.
export WIRE_MACHINE_BUTTONS_ENABLED="${WIRE_MACHINE_BUTTONS_ENABLED:-1}"
export WIRE_MACHINE_PLUS_GPIO="${WIRE_MACHINE_PLUS_GPIO:-14}"
export WIRE_MACHINE_MINUS_GPIO="${WIRE_MACHINE_MINUS_GPIO:-15}"

cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Stopping SurfaceAI server..."
    kill "$SERVER_PID"
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [ -n "$BROWSER_PID" ] && kill -0 "$BROWSER_PID" 2>/dev/null; then
    echo "Closing SurfaceAI browser..."
    kill "$BROWSER_PID" 2>/dev/null || true
  fi
}

on_signal() {
  exit 0
}

on_error() {
  local code=$?
  echo
  echo "SurfaceAI could not start. The command above failed with exit code $code."
  echo "Check the message above."
  if [ -t 0 ]; then
    echo "Press Enter to close this window."
    read -r
  fi
  exit "$code"
}

trap on_error ERR
trap cleanup EXIT
trap on_signal INT TERM

cd "$APP_DIR"

echo "SurfaceAI starting..."
echo "Project: $APP_DIR"
echo "Branch:  $BRANCH"

if [ "$UPDATE_ON_START" = "1" ] && command -v git >/dev/null 2>&1; then
  echo "Checking for updates..."
  if git fetch origin && git checkout "$BRANCH" && git pull --ff-only origin "$BRANCH"; then
    echo "Application is up to date."
  else
    echo "Update check unavailable; starting the installed version."
  fi
else
  echo "Using the installed project version (automatic Git updates disabled)."
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Virtual environment not found at .venv"
  echo "Please run the first-time installation commands before using the launcher."
  if [ -t 0 ]; then
    read -r -p "Press Enter to close..."
  fi
  exit 1
fi

".venv/bin/python" -m py_compile app.py

if pgrep -f "uvicorn app:app.*--port ${PORT}" >/dev/null 2>&1; then
    echo "Server is already running."
else
    echo "Starting server..."
    ".venv/bin/python" -m uvicorn app:app --host 0.0.0.0 --port "$PORT" --no-access-log &
    SERVER_PID=$!
fi

echo "Waiting for web app..."
READY=0
for _ in $(seq 1 30); do
  if curl -fsS "$URL/status" 2>/dev/null | ".venv/bin/python" -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("model_ready") else 1)' 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done

if [ "$READY" != "1" ]; then
  echo "SurfaceAI did not become model-ready within 30 seconds."
  curl -fsS "$URL/status" 2>/dev/null || true
  exit 1
fi

echo "Opening $URL"
CHROMIUM_FLAGS=("$URL" "--no-first-run" "--disable-session-crashed-bubble")
if [ "$KIOSK_MODE" = "1" ]; then
  CHROMIUM_FLAGS+=("--kiosk" "--start-fullscreen")
fi

if command -v chromium-browser >/dev/null 2>&1; then
  chromium-browser "${CHROMIUM_FLAGS[@]}" >/dev/null 2>&1 &
  BROWSER_PID=$!
elif command -v chromium >/dev/null 2>&1; then
  chromium "${CHROMIUM_FLAGS[@]}" >/dev/null 2>&1 &
  BROWSER_PID=$!
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
  BROWSER_PID=$!
else
  echo "Open this URL manually: $URL"
fi

echo "SurfaceAI is running. Keep this window open while using the app."
if [ "$KIOSK_MODE" = "1" ]; then
  echo "Kiosk mode is enabled. Press Alt+F4 to leave Chromium."
fi
echo "Press Ctrl+C here only when you want to stop the server."
if [ -n "$SERVER_PID" ]; then
  wait "$SERVER_PID"
else
  while curl -fsS "$URL/status" >/dev/null 2>&1; do
    sleep 5
  done
fi
