#!/usr/bin/env bash
# First-time setup for macOS and non-Pi Linux manual-inspection mode.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON=python3.11
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "Python 3.11 was not found. Install 64-bit Python 3.11 and run this script again."
  exit 1
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)' 2>/dev/null; then
  echo "SurfaceAI desktop mode requires Python 3.11. Found: $($PYTHON --version)"
  exit 1
fi

VENV="$PROJECT_DIR/.surfaceai-venv"
if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r requirements.txt
exec "$VENV/bin/python" run_desktop.py "$@"
