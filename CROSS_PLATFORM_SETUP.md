# Cross Platform Manual Inspection

SurfaceAI supports upload-based inspection on Windows, macOS, and Linux. Raspberry Pi camera, GPIO capture, motor, and physical counter buttons are optional hardware features and are not required for manual inspection.

## Supported desktop baseline

Use 64-bit Python 3.10, 3.11, or 3.12. Python 3.11 is the recommended common version for Windows, macOS, and Linux deployments.

## Windows PowerShell

```powershell
cd path\to\Wire-Defect-Detection-V2
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run_desktop.py
```

If PowerShell blocks activation, use `Set-ExecutionPolicy -Scope Process Bypass` for the current terminal, then activate again. Install the Microsoft Visual C++ Redistributable if TensorFlow reports a missing DLL.

## macOS and Linux

```bash
cd /path/to/Wire-Defect-Detection-V2
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run_desktop.py
```

Open `http://127.0.0.1:8000/ui/` if the browser does not open automatically. Use **Select Image** and **Inspect Selected**. The camera stream and hardware controls are expected to be unavailable on regular computers.

## Verification

```bash
python -c "import tensorflow as tf; print(tf.__version__)"
python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/status'))['model_ready'])"
```

The second command should print `True` after the server has finished loading the model.
