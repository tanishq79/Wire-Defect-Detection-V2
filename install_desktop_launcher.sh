#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${SURFACEAI_APP_DIR:-$HOME/Desktop/Wire-Defect-Detection-V2}"
DESKTOP_DIR="$HOME/Desktop"
LAUNCHER_PATH="$DESKTOP_DIR/SurfaceAI.desktop"

cd "$APP_DIR"
chmod +x run_pi.sh start_surfaceai_desktop.sh

mkdir -p "$DESKTOP_DIR"

cat > "$LAUNCHER_PATH" <<EOF
[Desktop Entry]
Type=Application
Name=SurfaceAI
Comment=Start SurfaceAI wire inspection
Path=$APP_DIR
Exec=lxterminal -t SurfaceAI -e bash -lc '$APP_DIR/start_surfaceai_desktop.sh'
Icon=applications-graphics
Terminal=false
Categories=Utility;
EOF

chmod +x "$LAUNCHER_PATH"

echo "Desktop launcher created:"
echo "$LAUNCHER_PATH"
echo
echo "Double-click SurfaceAI on the desktop to update, start the server, and open the browser."
