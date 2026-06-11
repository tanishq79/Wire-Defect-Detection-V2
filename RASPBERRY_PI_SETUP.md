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
sudo apt install -y git python3-venv python3-pip python3-picamera2 libatlas-base-dev libopenblas-dev libjpeg-dev zlib1g-dev

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

```bash
source .venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open the dashboard on the Pi:

```text
http://127.0.0.1:8000
```

From another device on the same network, replace `127.0.0.1` with the Pi IP address.

## 4. Input Modes

- Upload an image through the dashboard and click `Run Inspection`.
- Enter a stored image path in the dashboard and click `Inspect`.
- Click `Capture From Camera` to capture from the Raspberry Pi camera using `picamera2`.

By default, relative stored-image paths are resolved under `images/`. Override this before starting the API:

```bash
export WIRE_IMAGE_ROOT=/home/pi/wire_images
uvicorn app:app --host 0.0.0.0 --port 8000
```

## 5. Saved Inspection Records

Each inspection is logged to:

```text
inspection_data/inspection_log.jsonl
```

Uploaded images are copied to:

```text
inspection_data/uploads/
```

Recent records can be checked from the API:

```bash
curl http://127.0.0.1:8000/history
```

## 6. Updating On The Raspberry Pi

If the changes are pushed to the GitHub repo:

```bash
cd ~/Desktop/Wire-Defect-Detection-V2
git pull
source .venv/bin/activate
python -m py_compile app.py
uvicorn app:app --host 0.0.0.0 --port 8000
```
