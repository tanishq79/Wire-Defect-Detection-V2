# Raspberry Pi 4 Deployment Notes

## 1. Compatibility Check

Run this first on the Raspberry Pi over VNC/terminal:

```bash
printf "\n== OS ==\n"; cat /etc/os-release
printf "\n== Kernel / Architecture ==\n"; uname -a; dpkg --print-architecture; getconf LONG_BIT
printf "\n== Raspberry Pi model ==\n"; cat /proc/device-tree/model; echo
printf "\n== CPU / RAM ==\n"; lscpu | sed -n '1,12p'; free -h
printf "\n== Disk ==\n"; df -h /
printf "\n== Python ==\n"; python3 --version; which python3
printf "\n== Camera stack ==\n"; command -v rpicam-hello || command -v libcamera-hello || true
printf "\n== Camera detection ==\n"; rpicam-hello --list-cameras 2>/dev/null || libcamera-hello --list-cameras 2>/dev/null || echo "No rpicam/libcamera command found"
printf "\n== Python camera module ==\n"; python3 - <<'PY'
try:
    import picamera2
    print("picamera2: OK")
except Exception as exc:
    print("picamera2:", exc)
PY
```

Expected result for the current project:

- Raspberry Pi 4 should report `aarch64` / `arm64` and 64-bit OS.
- Python should ideally be 3.10 or 3.11.
- `rpicam-hello --list-cameras` or `libcamera-hello --list-cameras` should show the Raspberry Pi HQ camera.
- At least 2 GB RAM can run inference, but 4 GB or 8 GB is safer. Use swap if TensorFlow install or model load struggles.

## 2. First Install Pass

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip python3-picamera2 python3-gpiozero libatlas-base-dev libopenblas-dev libjpeg-dev zlib1g-dev

git clone https://github.com/tanishq79/Wire-Defect-Detection-V2.git
cd Wire-Defect-Detection-V2

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install fastapi==0.110.0 uvicorn==0.27.1 numpy pillow python-multipart
pip install tensorflow
```

If `pip install tensorflow` fails on Raspberry Pi OS, capture the full error. TensorFlow wheel support depends heavily on OS version, Python version, and 64-bit architecture.

## 3. Run

Terminal run:

```bash
source .venv/bin/activate
./run_pi.sh
```

Open the dashboard on the Pi:

```text
http://127.0.0.1:8000
```

From another device on the same network, replace `127.0.0.1` with the Pi IP address.

## 3A. Desktop Launcher

Create the desktop icon:

```bash
cd ~/Desktop/Wire-Defect-Detection-V2
git fetch origin
git checkout main
git pull --ff-only origin main
chmod +x install_desktop_launcher.sh start_surfaceai_desktop.sh run_pi.sh
./install_desktop_launcher.sh
```

After that, double-click `SurfaceAI` on the Raspberry Pi desktop.

The launcher will:

- start the FastAPI server using `.venv`
- open the browser at `http://127.0.0.1:8000`
- keep a terminal open for logs and errors

It deliberately does not update Git automatically at boot, so a network problem or a local change cannot prevent the inspection app from opening. Update manually with `git pull --ff-only origin main` when you choose.

### Start automatically in full-screen kiosk mode

The same installer enables autostart. After running it once, SurfaceAI starts whenever the Raspberry Pi boots to the desktop, and Chromium opens with no browser controls in full-screen kiosk mode. Restart the Pi to test it:

```bash
sudo reboot
```

Press `Alt+F4` to leave Chromium if you need the desktop. To turn off autostart later:

```bash
rm ~/.config/autostart/SurfaceAI.desktop
```

## 4. Input Modes

- Upload an image through the dashboard and click `Run Inspection`.
- Enter a stored image path in the dashboard and click `Inspect`.
- Click `Start Preview` to view the live Raspberry Pi HQ camera feed.
- Click `Capture & Inspect` to capture a 1600 x 1200 still and save all three image variants before running prediction from the saved 224 x 224 input.
- Press the physical button wired between GPIO23 (physical pin 16) and GND to capture and inspect without touching the screen. Its result appears in the dashboard automatically.

All new inspection images live in one main folder, `images/` beside `app.py`:

```text
images/
├── 1600x1200/   # evidence
├── 640x320/     # processed dashboard previews
└── 224x224/     # processed model inputs
```

Each inspection creates three lossless PNGs with the same unique filename. The
model reads its saved 224 x 224 file. The dashboard retrieves the 640 x 320 file
and offers a link to the 1600 x 1200 evidence. Uploads and stored-path inspections
use the same flow as both camera capture buttons.

Relative image paths resolve under this main folder; a bare generated filename
also resolves in `1600x1200/`. Absolute legacy paths are still accepted.
Override the main folder before starting the API:

```bash
export WIRE_IMAGE_ROOT=/home/pi/wire_images
uvicorn app:app --host 0.0.0.0 --port 8000
```

`WIRE_CAPTURE_DIR` no longer controls a separate output directory. If your launcher
sets it, replace it with `WIRE_IMAGE_ROOT` to move all three folders together.
`WIRE_INSPECTION_DIR` still controls JSONL history, separately from image files.

The live camera stream remains in memory, using 640 x 480 by default; it does not
save every frame. The saved dashboard preview is always exactly 640 x 320, with
padding to retain the entire image. Evidence is fitted to 1600 x 1200 with padding
where needed; camera stills already match that size. Model input retains the
existing direct 224 x 224 resize and enhancement settings.

Camera endpoints:

```text
GET  /camera/status
GET  /camera/stream
POST /capture
POST /camera/stop
GET  /images/{resolution}/{filename}
```

## 5. Saved Inspection Records

Each inspection is logged to:

```text
inspection_data/inspection_log.jsonl
```

No new images are written to `inspection_data/uploads/`,
`inspection_data/processed/`, or `~/Desktop/CapturedImages`. Old files and history
are not deleted or bulk-converted. To inspect an old image, submit its absolute
path with `Inspect Path`; this creates a new three-resolution bundle while
preserving the original file and old history entries.

New log entries include all three image paths/URLs and the processing settings.
Existing log entries remain readable. See [IMAGE_STORAGE.md](IMAGE_STORAGE.md)
for API fields, storage details, and verification commands.

Recent records can be checked from the API:

```bash
curl http://127.0.0.1:8000/history
```

## 6. Updating On The Raspberry Pi

If the changes are pushed to the GitHub repo:

```bash
cd ~/Desktop/Wire-Defect-Detection-V2
git fetch origin
git checkout main
git pull --ff-only origin main
source .venv/bin/activate
./run_pi.sh
```

To confirm the exact Git version running on the Pi:

```bash
cd ~/Desktop/Wire-Defect-Detection-V2
git branch --show-current
git log --oneline -1
git status --short
```
