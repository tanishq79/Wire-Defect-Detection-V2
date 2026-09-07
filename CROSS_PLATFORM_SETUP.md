# Cross Platform Manual Inspection

SurfaceAI supports upload-based inspection on Windows, macOS, and Linux. Raspberry Pi camera, GPIO capture, motor, and physical counter buttons are optional hardware features and are not required for manual inspection.

## Supported desktop baseline

Use 64-bit Python 3.11. This is the tested common version for Windows, macOS, and Linux deployments.

## Windows PowerShell

```powershell
cd path\to\Wire-Defect-Detection-V2
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_surfaceai_windows.ps1
```

For daily use, run `Set-ExecutionPolicy -Scope Process Bypass -Force` followed by `./start_surfaceai_windows.ps1`. These scripts never pull from Git automatically. Install the Microsoft Visual C++ Redistributable if TensorFlow reports a missing DLL.

If port 8000 is occupied, use `./start_surfaceai_windows.ps1 -Port 8001` and open `http://127.0.0.1:8001/ui/`.

## macOS and Linux

```bash
cd /path/to/Wire-Defect-Detection-V2
bash ./setup_surfaceai_desktop.sh
```

The script creates a clean `.surfaceai-venv`, uses Python 3.11, and runs macOS inference on CPU. TensorFlow Metal is not installed because incompatible Metal plug-ins can prevent the application from launching.

Open `http://127.0.0.1:8000/ui/` if the browser does not open automatically. Use **Select Image** and **Inspect Selected**. The camera stream and hardware controls are expected to be unavailable on regular computers.

If port 8000 is occupied, use `python run_desktop.py --port 8001` and open `http://127.0.0.1:8001/ui/`.

## Verification

```bash
python -c "import tensorflow as tf; print(tf.__version__)"
python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/status'))['model_ready'])"
```

The second command should print `True` after the server has finished loading the model.
