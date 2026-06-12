from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import io
import json
import os
import platform
import threading
import time
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import tensorflow as tf
from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

import numpy as np
from PIL import Image, UnidentifiedImageError

app = FastAPI(title="SurfaceAI Wire Inspection API", version="2.1")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load best trained model
model = tf.keras.models.load_model(
    "best_wire_model.keras",
    compile=False
)

IMG_SIZE = 224
IMAGE_ROOT = Path(os.getenv("WIRE_IMAGE_ROOT", "images")).resolve()
INSPECTION_DIR = Path(os.getenv("WIRE_INSPECTION_DIR", "inspection_data")).resolve()
UPLOAD_DIR = INSPECTION_DIR / "uploads"
CAPTURE_DIR = Path(os.getenv("WIRE_CAPTURE_DIR", str(Path.home() / "Desktop" / "CapturedImages"))).resolve()
LOG_FILE = INSPECTION_DIR / "inspection_log.jsonl"
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

if Path("frontend").exists():
    app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")


def predict_image(img: Image.Image):
    img = img.convert("RGB").resize((IMG_SIZE, IMG_SIZE))

    img_array = image.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)
    img_array = preprocess_input(img_array)

    pred = model.predict(img_array, verbose=0)
    score = float(pred[0][0])

    if score >= 0.5:
        prediction = "ok_wire"
        confidence = score * 100
    else:
        prediction = "defected_wire"
        confidence = (1 - score) * 100

    return {
        "prediction": prediction,
        "confidence": round(confidence, 2),
        "raw_score": round(score, 4),
    }


def log_inspection(result: dict, source: str, source_name: Optional[str] = None):
    INSPECTION_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "source_name": source_name,
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "raw_score": result["raw_score"],
    }
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")
    return record


def read_recent_inspections(limit: int = 50):
    if not LOG_FILE.exists():
        return []

    records = []
    with LOG_FILE.open("r", encoding="utf-8") as log:
        for line in log:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return records[-limit:][::-1]


def open_image_from_bytes(contents: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(contents)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a readable image") from exc


def open_image_from_path(path: Path) -> Image.Image:
    try:
        return Image.open(path).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail=f"Image is not readable: {path}") from exc


def save_upload(contents: bytes, filename: Optional[str]):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        suffix = ".jpg"

    saved_path = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{suffix}"
    saved_path.write_bytes(contents)
    return saved_path


class CameraManager:
    def __init__(self):
        self.picam2 = None
        self.lock = threading.Lock()
        self.preview_size = (768, 432)
        self.still_size = (4056, 3040)

    def start(self):
        if self.picam2 is not None:
            return

        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail="picamera2 is not installed. Install it with: sudo apt install -y python3-picamera2",
            ) from exc

        camera = Picamera2()
        config = camera.create_preview_configuration(
            main={"size": self.preview_size, "format": "RGB888"}
        )
        camera.configure(config)
        camera.start()
        time.sleep(1)
        self.picam2 = camera

    def stop(self):
        if self.picam2 is None:
            return

        with self.lock:
            self.picam2.stop()
            self.picam2.close()
            self.picam2 = None

    def status(self):
        if self.picam2 is None:
            try:
                from picamera2 import Picamera2  # noqa: F401
                return {
                    "available": True,
                    "model": "imx477",
                    "started": False,
                    "preview_size": self.preview_size,
                    "still_size": self.still_size,
                    "capture_dir": str(CAPTURE_DIR),
                }
            except Exception as exc:
                return {
                    "available": False,
                    "started": False,
                    "error": str(exc),
                    "capture_dir": str(CAPTURE_DIR),
                }

        try:
            properties = self.picam2.camera_properties if self.picam2 else {}
            return {
                "available": True,
                "model": properties.get("Model", "unknown"),
                "started": True,
                "preview_size": self.preview_size,
                "still_size": self.still_size,
                "capture_dir": str(CAPTURE_DIR),
            }
        except Exception as exc:
            return {
                "available": False,
                "started": False,
                "error": str(exc),
                "capture_dir": str(CAPTURE_DIR),
            }

    def get_frame_image(self) -> Image.Image:
        self.start()
        with self.lock:
            frame = self.picam2.capture_array()

        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = frame[:, :, :3]

        return Image.fromarray(frame).convert("RGB")

    def get_frame_jpeg(self) -> bytes:
        img = self.get_frame_image()
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=80)
        return output.getvalue()

    def capture_image(self) -> Path:
        self.start()
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".png"
        output_path = CAPTURE_DIR / filename

        with self.lock:
            still_config = self.picam2.create_still_configuration(
                main={"size": self.still_size, "format": "RGB888"}
            )
            image_array = self.picam2.switch_mode_and_capture_array(still_config)

        if image_array.ndim == 3 and image_array.shape[2] == 4:
            image_array = image_array[:, :, :3]

        Image.fromarray(image_array).convert("RGB").save(output_path)
        return output_path


camera_manager = CameraManager()


def resolve_image_path(path_value: str) -> Path:
    if not path_value:
        raise HTTPException(status_code=400, detail="Missing image path")

    requested = Path(path_value).expanduser()
    if not requested.is_absolute():
        requested = IMAGE_ROOT / requested

    resolved = requested.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found: {path_value}")

    if resolved.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    return resolved


def capture_from_picamera2() -> Path:
    return camera_manager.capture_image()


def mjpeg_frames():
    while True:
        try:
            frame = camera_manager.get_frame_jpeg()
        except Exception:
            break

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )
        time.sleep(0.08)

@app.get("/")
async def root():
    if Path("frontend/index.html").exists():
        return RedirectResponse(url="/ui/")

    return {"message": "Wire Defect Detection API Running", "docs": "/docs"}


@app.get("/api")
async def api_info():
    return {
        "message": "Wire Defect Detection API Running",
        "docs": "/docs",
        "status": "/status",
        "ui": "/ui/",
    }

@app.get("/status")
async def status():
    return {
        "model_name": "MobileNetV2",
        "model_loaded": True,
        "api_connected": True,
        "device": platform.machine(),
        "platform": platform.platform(),
        "tensorflow_version": tf.__version__,
        "gpu_available": bool(tf.config.list_physical_devices("GPU")),
        "image_root": str(IMAGE_ROOT),
        "inspection_dir": str(INSPECTION_DIR),
        "capture_dir": str(CAPTURE_DIR),
        "ui_available": Path("frontend/index.html").exists(),
    }

@app.post("/predict")
async def predict(file: UploadFile = File(...)):

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    img = open_image_from_bytes(contents)
    saved_path = save_upload(contents, file.filename)
    result = predict_image(img)
    result["source"] = "upload"
    result["filename"] = file.filename
    result["saved_path"] = str(saved_path)
    result["log"] = log_inspection(result, "upload", file.filename)
    return result


@app.post("/predict-path")
async def predict_path(path: str):
    image_path = resolve_image_path(path)
    img = open_image_from_path(image_path)
    result = predict_image(img)
    result["source"] = "path"
    result["path"] = str(image_path)
    result["log"] = log_inspection(result, "path", str(image_path))
    return result


@app.post("/capture")
async def capture():
    image_path = capture_from_picamera2()
    img = open_image_from_path(image_path)
    result = predict_image(img)
    result["source"] = "camera"
    result["path"] = str(image_path)
    result["log"] = log_inspection(result, "camera", str(image_path))
    return result


@app.get("/camera/status")
async def camera_status():
    return camera_manager.status()


@app.get("/camera/stream")
async def camera_stream():
    return StreamingResponse(
        mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.post("/camera/stop")
async def camera_stop():
    camera_manager.stop()
    return {"stopped": True}


@app.get("/history")
async def history(limit: int = 50):
    limit = max(1, min(limit, 500))
    return {"items": read_recent_inspections(limit), "limit": limit}
