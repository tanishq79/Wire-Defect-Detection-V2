#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${SURFACEAI_APP_DIR:-$HOME/Desktop/Wire-Defect-Detection-V2}"
DESKTOP_DIR="$HOME/Desktop"
LAUNCHER_PATH="$DESKTOP_DIR/SurfaceAI.desktop"
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_PATH="$AUTOSTART_DIR/SurfaceAI.desktop"

cd "$APP_DIR"
chmod +x run_pi.sh start_surfaceai_desktop.sh

mkdir -p "$DESKTOP_DIR"

cat > "$LAUNCHER_PATH" <<EOF
[Desktop Entry]
Type=Application
Name=SurfaceAI
Comment=Start SurfaceAI wire inspection
Path=$APP_DIR
Exec=lxterminal -t SurfaceAI -e bash -lc 'SURFACEAI_UPDATE_ON_START=1 $APP_DIR/start_surfaceai_desktop.sh'
Icon=applications-graphics
Terminal=false
Categories=Utility;
EOF

chmod +x "$LAUNCHER_PATH"

mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_PATH" <<EOF
[Desktop Entry]
Type=Application
Name=SurfaceAI Kiosk
Comment=Start SurfaceAI automatically in full-screen kiosk mode
Path=$APP_DIR
Exec=env SURFACEAI_KIOSK=1 $APP_DIR/start_surfaceai_desktop.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

chmod +x "$AUTOSTART_PATH"

echo "Desktop launcher created:"
echo "$LAUNCHER_PATH"
echo
echo "Autostart enabled (full-screen kiosk mode):"
echo "$AUTOSTART_PATH"
echo
echo "SurfaceAI will now start automatically at desktop login in full-screen kiosk mode."
echo "The desktop icon checks and fast-forwards the main branch before starting."
echo "Autostart uses the installed version so a network outage cannot block boot."
