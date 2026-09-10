#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${SURFACEAI_PORT:-8000}"

# GPIO14/GPIO15 are the installed machine counter buttons on the Raspberry Pi.
# Keep an explicit environment override so a different installation can disable
# them with WIRE_MACHINE_BUTTONS_ENABLED=0 without editing this launcher.
export WIRE_MACHINE_BUTTONS_ENABLED="${WIRE_MACHINE_BUTTONS_ENABLED:-1}"
export WIRE_MACHINE_PLUS_GPIO="${WIRE_MACHINE_PLUS_GPIO:-14}"
export WIRE_MACHINE_MINUS_GPIO="${WIRE_MACHINE_MINUS_GPIO:-15}"

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
