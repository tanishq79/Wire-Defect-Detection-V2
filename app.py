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

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import tensorflow as tf
from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, UnidentifiedImageError

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
PROCESSED_DIR = INSPECTION_DIR / "processed"
CAPTURE_DIR = Path(os.getenv("WIRE_CAPTURE_DIR", str(Path.home() / "Desktop" / "CapturedImages"))).resolve()
STILL_WIDTH = int(os.getenv("WIRE_STILL_WIDTH", "1600"))
STILL_HEIGHT = int(os.getenv("WIRE_STILL_HEIGHT", "1200"))
LOG_FILE = INSPECTION_DIR / "inspection_log.jsonl"
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

if Path("frontend").exists():
    app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def build_processing_settings(
    brightness: float = 0,
    contrast: float = 0,
    sharpness: float = 0,
    mask_strength: float = 0,
):
    return {
        "brightness": clamp(brightness, -50, 50),
        "contrast": clamp(contrast, -50, 50),
        "sharpness": clamp(sharpness, 0, 100),
        "mask_strength": clamp(mask_strength, 0, 100),
    }


def apply_image_enhancements(img: Image.Image, settings: dict) -> Image.Image:
    enhanced = img.convert("RGB")
    brightness = 1 + settings["brightness"] / 100
    contrast = 1 + settings["contrast"] / 100
    sharpness = 1 + settings["sharpness"] / 45

    enhanced = ImageEnhance.Brightness(enhanced).enhance(brightness)
    enhanced = ImageEnhance.Contrast(enhanced).enhance(contrast)
    enhanced = ImageEnhance.Sharpness(enhanced).enhance(sharpness)
    return enhanced


def build_wire_mask(img: Image.Image) -> Image.Image:
    gray = img.convert("L")
    radius = max(9, min(gray.size) // 28)
    background = gray.filter(ImageFilter.GaussianBlur(radius=radius))
    diff = ImageChops.difference(gray, background)
    arr = np.asarray(diff, dtype=np.float32)
    threshold = max(10, float(arr.mean() + arr.std() * 0.65))
    mask = diff.point(lambda px: 255 if px >= threshold else 0, mode="L")
    mask = mask.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(radius=3))
    return mask


def suppress_background(img: Image.Image, mask_strength: float) -> Image.Image:
    if mask_strength <= 0:
        return img

    mask = build_wire_mask(img)
    alpha = mask.point(lambda px: int(px * (mask_strength / 100)), mode="L")
    background = Image.new("RGB", img.size, (18, 24, 28))
    muted = Image.blend(img, background, 0.72)
    return Image.composite(img, muted, alpha)


def draw_wire_overlay(img: Image.Image, settings: dict) -> Image.Image:
    enhanced = apply_image_enhancements(img, settings)
    mask = build_wire_mask(enhanced)
    edge = mask.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    edge = edge.point(lambda px: 185 if px > 28 else 0, mode="L")
    overlay = Image.new("RGB", enhanced.size, (251, 191, 36))
    return Image.composite(overlay, enhanced, edge)


def prepare_image_for_model(img: Image.Image, settings: Optional[dict] = None):
    settings = settings or build_processing_settings()
    processed = apply_image_enhancements(img, settings)
    processed = suppress_background(processed, settings["mask_strength"])
    return processed, settings


def save_processed_image(img: Image.Image, stem: str = "processed") -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)[:48] or "processed"
    path = PROCESSED_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_stem}.jpg"
    img.save(path, format="JPEG", quality=92)
    return path


def predict_image(img: Image.Image, processing: Optional[dict] = None):
    processed_img, processing_settings = prepare_image_for_model(img, processing)
    img = processed_img.resize((IMG_SIZE, IMG_SIZE))

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
        "processing": processing_settings,
    }


def warm_up_model():
    dummy = np.zeros((1, IMG_SIZE, IMG_SIZE, 3), dtype=np.float32)
    try:
        model.predict(dummy, verbose=0)
    except Exception:
        pass


warm_up_model()


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
        self.still_size = (STILL_WIDTH, STILL_HEIGHT)

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

    def get_frame_jpeg(self, processing: Optional[dict] = None, wire_overlay: bool = True) -> bytes:
        img = self.get_frame_image()
        if processing:
            img = apply_image_enhancements(img, processing)
        if wire_overlay:
            img = draw_wire_overlay(img, processing or build_processing_settings())
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=80)
        return output.getvalue()

    def capture_image(self) -> Path:
        self.start()
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
        output_path = CAPTURE_DIR / filename

        with self.lock:
            still_config = self.picam2.create_still_configuration(
                main={"size": self.still_size, "format": "RGB888"}
            )
            image_array = self.picam2.switch_mode_and_capture_array(still_config)

        if image_array.ndim == 3 and image_array.shape[2] == 4:
            image_array = image_array[:, :, :3]

        Image.fromarray(image_array).convert("RGB").save(output_path, format="JPEG", quality=94)
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


def mjpeg_frames(processing: Optional[dict] = None, wire_overlay: bool = True):
    while True:
        try:
            frame = camera_manager.get_frame_jpeg(processing, wire_overlay)
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
async def predict(
    file: UploadFile = File(...),
    brightness: float = Form(0),
    contrast: float = Form(0),
    sharpness: float = Form(0),
    mask_strength: float = Form(0),
):

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    img = open_image_from_bytes(contents)
    saved_path = save_upload(contents, file.filename)
    processing = build_processing_settings(brightness, contrast, sharpness, mask_strength)
    result = predict_image(img, processing)
    if processing["mask_strength"] > 0 or any(processing[key] != 0 for key in ("brightness", "contrast", "sharpness")):
        processed_img, _ = prepare_image_for_model(img, processing)
        result["processed_path"] = str(save_processed_image(processed_img, Path(file.filename or "upload").stem))
    result["source"] = "upload"
    result["filename"] = file.filename
    result["saved_path"] = str(saved_path)
    result["log"] = log_inspection(result, "upload", file.filename)
    return result


@app.post("/predict-path")
async def predict_path(
    path: str,
    brightness: float = 0,
    contrast: float = 0,
    sharpness: float = 0,
    mask_strength: float = 0,
):
    image_path = resolve_image_path(path)
    img = open_image_from_path(image_path)
    processing = build_processing_settings(brightness, contrast, sharpness, mask_strength)
    result = predict_image(img, processing)
    if processing["mask_strength"] > 0 or any(processing[key] != 0 for key in ("brightness", "contrast", "sharpness")):
        processed_img, _ = prepare_image_for_model(img, processing)
        result["processed_path"] = str(save_processed_image(processed_img, image_path.stem))
    result["source"] = "path"
    result["path"] = str(image_path)
    result["log"] = log_inspection(result, "path", str(image_path))
    return result


@app.post("/capture")
async def capture(
    brightness: float = 0,
    contrast: float = 0,
    sharpness: float = 0,
    mask_strength: float = 0,
):
    image_path = capture_from_picamera2()
    img = open_image_from_path(image_path)
    processing = build_processing_settings(brightness, contrast, sharpness, mask_strength)
    result = predict_image(img, processing)
    if processing["mask_strength"] > 0 or any(processing[key] != 0 for key in ("brightness", "contrast", "sharpness")):
        processed_img, _ = prepare_image_for_model(img, processing)
        result["processed_path"] = str(save_processed_image(processed_img, image_path.stem))
    result["source"] = "camera"
    result["path"] = str(image_path)
    result["log"] = log_inspection(result, "camera", str(image_path))
    return result


@app.get("/camera/status")
async def camera_status():
    return camera_manager.status()


@app.get("/camera/stream")
async def camera_stream(
    brightness: float = 0,
    contrast: float = 0,
    sharpness: float = 0,
    wire_overlay: bool = True,
):
    processing = build_processing_settings(brightness, contrast, sharpness, 0)
    return StreamingResponse(
        mjpeg_frames(processing, wire_overlay),
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
