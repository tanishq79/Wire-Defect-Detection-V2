from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import io
import json
import os
import platform
import tempfile
import threading
import time
import uuid
import zipfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

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

def install_keras_legacy_config_shims():
    depthwise_layer = tf.keras.layers.DepthwiseConv2D
    original_from_config = depthwise_layer.from_config

    if getattr(depthwise_layer, "_surfaceai_legacy_shim", False):
        return

    def depthwise_from_config(cls, config):
        config = dict(config)
        config.pop("groups", None)
        return original_from_config(config)

    depthwise_layer.from_config = classmethod(depthwise_from_config)
    depthwise_layer._surfaceai_legacy_shim = True


def sanitize_keras_config(value):
    if isinstance(value, list):
        return [sanitize_keras_config(item) for item in value]

    if not isinstance(value, dict):
        return value

    cleaned = {key: sanitize_keras_config(item) for key, item in value.items()}
    class_name = cleaned.get("class_name")
    config = cleaned.get("config")

    if isinstance(config, dict):
        if class_name == "DepthwiseConv2D":
            config.pop("groups", None)
        if class_name == "BatchNormalization" and isinstance(config.get("axis"), list) and len(config["axis"]) == 1:
            config["axis"] = config["axis"][0]

    return cleaned


def load_sanitized_keras_archive(model_path: str):
    with tempfile.TemporaryDirectory(prefix="surfaceai_model_") as tmp_dir:
        with zipfile.ZipFile(model_path) as archive:
            archive.extractall(tmp_dir)

        config_path = Path(tmp_dir) / "config.json"
        weights_path = Path(tmp_dir) / "model.weights.h5"

        with config_path.open("r", encoding="utf-8") as config_file:
            config = sanitize_keras_config(json.load(config_file))

        rebuilt_model = tf.keras.models.model_from_json(json.dumps(config))
        rebuilt_model.load_weights(str(weights_path))
        return rebuilt_model


def load_wire_model():
    install_keras_legacy_config_shims()
    try:
        return tf.keras.models.load_model("best_wire_model.keras", compile=False, safe_mode=False)
    except Exception as exc:
        print(f"Standard model load failed, trying sanitized legacy load: {exc}", flush=True)
        return load_sanitized_keras_archive("best_wire_model.keras")


# Load best trained model
try:
    model = load_wire_model()
except Exception as exc:
    print(f"SurfaceAI model failed to load: {exc}", flush=True)
    raise

IMG_SIZE = 224
IMAGE_ROOT = Path(os.getenv("WIRE_IMAGE_ROOT", "images")).resolve()
INSPECTION_DIR = Path(os.getenv("WIRE_INSPECTION_DIR", "inspection_data")).resolve()
UPLOAD_DIR = INSPECTION_DIR / "uploads"
PROCESSED_DIR = INSPECTION_DIR / "processed"
CAPTURE_DIR = Path(os.getenv("WIRE_CAPTURE_DIR", str(Path.home() / "Desktop" / "CapturedImages"))).resolve()
<<<<<<< HEAD
# Production inspection captures are fixed at this resolution. Keeping these
# constants non-configurable prevents a launcher environment from silently
# changing the resolution of stored evidence images.
STILL_WIDTH = 1600
STILL_HEIGHT = 1200
PREVIEW_WIDTH = int(os.getenv("WIRE_PREVIEW_WIDTH", "640"))
PREVIEW_HEIGHT = int(os.getenv("WIRE_PREVIEW_HEIGHT", "480"))
STREAM_FPS = max(1, min(30, int(os.getenv("WIRE_STREAM_FPS", "8"))))
STREAM_JPEG_QUALITY = max(35, min(90, int(os.getenv("WIRE_STREAM_JPEG_QUALITY", "68"))))
# The live stream uses the lightweight preview configuration, but every
# inspection capture uses the dedicated 1600x1200 still configuration.
CAPTURE_MODE = "still"
=======
STILL_WIDTH = int(os.getenv("WIRE_STILL_WIDTH", "1600"))
STILL_HEIGHT = int(os.getenv("WIRE_STILL_HEIGHT", "1200"))
PREVIEW_WIDTH = int(os.getenv("WIRE_PREVIEW_WIDTH", "640"))
PREVIEW_HEIGHT = int(os.getenv("WIRE_PREVIEW_HEIGHT", "360"))
STREAM_FPS = max(1, min(30, int(os.getenv("WIRE_STREAM_FPS", "8"))))
STREAM_JPEG_QUALITY = max(35, min(90, int(os.getenv("WIRE_STREAM_JPEG_QUALITY", "68"))))
CAPTURE_MODE = os.getenv("WIRE_CAPTURE_MODE", "preview").strip().lower()
>>>>>>> 1c30d2e749e35641449d5b252c6ab3f8f0004dc6
GPIO_BUTTON_PIN = int(os.getenv("WIRE_BUTTON_GPIO", "23"))
GPIO_BUTTON_ENABLED = os.getenv("WIRE_BUTTON_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
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
        self.preview_size = (PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self.still_size = (STILL_WIDTH, STILL_HEIGHT)
        self.camera_index = int(os.getenv("WIRE_CAMERA_INDEX", "0"))
        self.last_error = None

    def _picamera2_class(self):
        try:
            from picamera2 import Picamera2
            return Picamera2
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail="picamera2 is not installed. Install it with: sudo apt install -y python3-picamera2",
            ) from exc

    def detected_cameras(self):
        Picamera2 = self._picamera2_class()
        try:
            return Picamera2.global_camera_info()
        except Exception as exc:
            self.last_error = str(exc)
            return []

    def _create_camera_config(self, camera, mode: str):
        if mode == "still":
            config_factory = camera.create_still_configuration
            size = self.still_size
        else:
            config_factory = camera.create_preview_configuration
            size = self.preview_size

        attempts = [
            {"size": size, "format": "RGB888"},
            {"size": size},
        ]
        last_exc = None
        for main_config in attempts:
            try:
                config = config_factory(main=main_config)
                return config
            except Exception as exc:
                last_exc = exc
                print(f"Camera {mode} config failed with {main_config}: {exc}", flush=True)

        raise last_exc

    def start(self):
        if self.picam2 is not None:
            return

        with self.lock:
            if self.picam2 is not None:
                return

            Picamera2 = self._picamera2_class()
            cameras = self.detected_cameras()
            if not cameras:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "No camera detected by Picamera2. Confirm rpicam-hello --list-cameras works, "
                        "then restart SurfaceAI."
                    ),
                )

            if self.camera_index >= len(cameras):
                raise HTTPException(
                    status_code=503,
                    detail=f"WIRE_CAMERA_INDEX={self.camera_index} is invalid. Detected {len(cameras)} camera(s).",
                )

            camera = None
            try:
                camera = Picamera2(self.camera_index)
                config = self._create_camera_config(camera, "preview")
                camera.configure(config)
                camera.start()
                time.sleep(1)
                self.picam2 = camera
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                print(f"Camera failed to start: {exc}", flush=True)
                try:
                    if camera is not None:
                        camera.close()
                except Exception:
                    pass
                raise HTTPException(status_code=503, detail=f"Camera failed to start: {exc}") from exc

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
                cameras = self.detected_cameras()
                if not cameras:
                    return {
                        "available": False,
                        "started": False,
                        "camera_index": self.camera_index,
                        "cameras": [],
                        "error": self.last_error or "No camera detected by Picamera2",
                        "capture_dir": str(CAPTURE_DIR),
                    }

                selected = cameras[min(self.camera_index, len(cameras) - 1)]
                return {
                    "available": True,
                    "model": selected.get("Model", "unknown"),
                    "started": False,
                    "camera_index": self.camera_index,
                    "cameras": cameras,
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
                "camera_index": self.camera_index,
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

    def get_frame_jpeg(self, processing: Optional[dict] = None, wire_overlay: bool = False) -> bytes:
        img = self.get_frame_image()
        if processing:
            img = apply_image_enhancements(img, processing)
        if wire_overlay:
            img = draw_wire_overlay(img, processing or build_processing_settings())
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=STREAM_JPEG_QUALITY, optimize=True)
        return output.getvalue()

    def capture_image(self) -> Path:
        self.start()
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
        output_path = CAPTURE_DIR / filename

<<<<<<< HEAD
        with self.lock:
            still_config = self._create_camera_config(self.picam2, "still")
            image_array = self.picam2.switch_mode_and_capture_array(still_config)
=======
        if CAPTURE_MODE == "still":
            with self.lock:
                still_config = self._create_camera_config(self.picam2, "still")
                image_array = self.picam2.switch_mode_and_capture_array(still_config)
        else:
            with self.lock:
                image_array = self.picam2.capture_array()
>>>>>>> 1c30d2e749e35641449d5b252c6ab3f8f0004dc6

        if image_array.ndim == 3 and image_array.shape[2] == 4:
            image_array = image_array[:, :, :3]

<<<<<<< HEAD
        actual_size = (int(image_array.shape[1]), int(image_array.shape[0]))
        if actual_size != self.still_size:
            raise RuntimeError(
                f"Camera returned {actual_size[0]}x{actual_size[1]}; "
                f"expected {self.still_size[0]}x{self.still_size[1]}. Image was not saved."
            )

=======
>>>>>>> 1c30d2e749e35641449d5b252c6ab3f8f0004dc6
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


def capture_and_inspect(processing: Optional[dict] = None) -> dict:
    """Capture a still, run the model, and record the inspection."""
    image_path = capture_from_picamera2()
    img = open_image_from_path(image_path)
    processing = processing or build_processing_settings()
    result = predict_image(img, processing)
    if processing["mask_strength"] > 0 or any(processing[key] != 0 for key in ("brightness", "contrast", "sharpness")):
        processed_img, _ = prepare_image_for_model(img, processing)
        result["processed_path"] = str(save_processed_image(processed_img, image_path.stem))
    result["source"] = "camera"
    result["path"] = str(image_path)
    result["log"] = log_inspection(result, "camera", str(image_path))
    return result


class HardwareCaptureButton:
    """Optional GPIO button that invokes the same capture-and-inspect workflow."""

    def __init__(self, pin: int):
        self.pin = pin
        self.button = None
        self.last_event = None
        self.last_error = None
        self._capture_lock = threading.Lock()
        self._event_lock = threading.Lock()

    def start(self):
        if not GPIO_BUTTON_ENABLED:
            print("Hardware capture button disabled by WIRE_BUTTON_ENABLED", flush=True)
            return
        if platform.system() != "Linux":
            print("Hardware capture button is only available on Raspberry Pi/Linux", flush=True)
            return
        try:
            from gpiozero import Button
            # Button wiring: GPIO23 (physical pin 16) to GND.
            self.button = Button(self.pin, pull_up=True, bounce_time=0.1)
            self.button.when_pressed = self._on_press
            print(f"Hardware capture button ready on GPIO{self.pin} (physical pin 16)", flush=True)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"Hardware capture button unavailable: {exc}", flush=True)

    def _on_press(self):
        if not self._capture_lock.acquire(blocking=False):
            print("Hardware button press ignored: capture already in progress", flush=True)
            return
        event_id = str(uuid.uuid4())
        with self._event_lock:
            self.last_event = {"id": event_id, "state": "capturing", "started_at": datetime.now(timezone.utc).isoformat()}
            self.last_error = None
        threading.Thread(target=self._capture, args=(event_id,), daemon=True).start()

    def _capture(self, event_id: str):
        try:
            print("Hardware button pressed: capturing wire image", flush=True)
            result = capture_and_inspect()
            with self._event_lock:
                self.last_event = {"id": event_id, "state": "complete", "completed_at": datetime.now(timezone.utc).isoformat(), "result": result}
            print(f"Hardware capture complete: {result['path']}", flush=True)
        except Exception as exc:
            self.last_error = str(exc)
            with self._event_lock:
                self.last_event = {"id": event_id, "state": "failed", "completed_at": datetime.now(timezone.utc).isoformat(), "error": str(exc)}
            print(f"Hardware capture failed: {exc}", flush=True)
        finally:
            self._capture_lock.release()

    def status(self) -> dict:
        with self._event_lock:
            event = dict(self.last_event) if self.last_event else None
        return {"enabled": GPIO_BUTTON_ENABLED, "available": self.button is not None, "pin": self.pin, "physical_pin": 16, "last_event": event, "error": self.last_error}


hardware_capture_button = HardwareCaptureButton(GPIO_BUTTON_PIN)
hardware_capture_button.start()


def mjpeg_frames(processing: Optional[dict] = None, wire_overlay: bool = False):
    while True:
        try:
            frame = camera_manager.get_frame_jpeg(processing, wire_overlay)
        except Exception as exc:
            camera_manager.last_error = str(exc)
            print(f"Camera stream stopped: {exc}", flush=True)
            break

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )
        time.sleep(1 / STREAM_FPS)

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
        "camera": camera_manager.status(),
        "stream_fps": STREAM_FPS,
        "stream_jpeg_quality": STREAM_JPEG_QUALITY,
        "capture_mode": CAPTURE_MODE,
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
    processing = build_processing_settings(brightness, contrast, sharpness, mask_strength)
    return capture_and_inspect(processing)


@app.get("/hardware-button/status")
async def hardware_button_status():
    return hardware_capture_button.status()


@app.get("/camera/status")
async def camera_status():
    return camera_manager.status()


@app.get("/camera/stream")
async def camera_stream(
    brightness: float = 0,
    contrast: float = 0,
    sharpness: float = 0,
    wire_overlay: bool = False,
):
    processing = build_processing_settings(brightness, contrast, sharpness, 0)
    camera_manager.start()
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
