from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import io
import json
import os
import platform
import tempfile
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
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
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="picamera2 is not installed. Install it on Raspberry Pi OS with: sudo apt install -y python3-picamera2",
        ) from exc

    output_dir = Path(tempfile.gettempdir()) / "wire_surface_captures"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "latest_capture.jpg"

    camera = Picamera2()
    try:
        config = camera.create_still_configuration(main={"size": (1920, 1080)})
        camera.configure(config)
        camera.start()
        camera.capture_file(str(output_path))
    finally:
        camera.close()

    return output_path

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


@app.get("/history")
async def history(limit: int = 50):
    limit = max(1, min(limit, 500))
    return {"items": read_recent_inspections(limit), "limit": limit}
