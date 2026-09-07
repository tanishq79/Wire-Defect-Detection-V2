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
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import tensorflow as tf
from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, UnidentifiedImageError
from image_storage import APP_DIR, IMAGE_SIZES, ImageStore, configured_path

app = FastAPI(title="SurfaceAI Wire Inspection API", version="2.1")


@app.middleware("http")
async def prevent_stale_frontend_assets(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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
        return tf.keras.models.load_model(str(APP_DIR / "best_wire_model.keras"), compile=False, safe_mode=False)
    except Exception as exc:
        print(f"Standard model load failed, trying sanitized legacy load: {exc}", flush=True)
        return load_sanitized_keras_archive(str(APP_DIR / "best_wire_model.keras"))


# Load best trained model
try:
    model = load_wire_model()
except Exception as exc:
    print(f"SurfaceAI model failed to load: {exc}", flush=True)
    raise

IMG_SIZE = 224
IMAGE_ROOT = configured_path("WIRE_IMAGE_ROOT", "images")
INSPECTION_DIR = configured_path("WIRE_INSPECTION_DIR", "inspection_data")
image_store = ImageStore(IMAGE_ROOT)
CAPTURE_DIR = IMAGE_ROOT / "1600x1200"
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
GPIO_BUTTON_PIN = int(os.getenv("WIRE_BUTTON_GPIO", "23"))
GPIO_BUTTON_ENABLED = os.getenv("WIRE_BUTTON_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
MOTOR_ENABLED = os.getenv("WIRE_MOTOR_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
MOTOR_UP_BUTTON_PIN = int(os.getenv("WIRE_MOTOR_UP_GPIO", "5"))
MOTOR_DOWN_BUTTON_PIN = int(os.getenv("WIRE_MOTOR_DOWN_GPIO", "25"))
MOTOR_ENABLE_PIN = int(os.getenv("WIRE_MOTOR_ENABLE_GPIO", "4"))
MOTOR_STEP_PIN = int(os.getenv("WIRE_MOTOR_STEP_GPIO", "18"))
MOTOR_DIRECTION_PIN = int(os.getenv("WIRE_MOTOR_DIRECTION_GPIO", "24"))
MOTOR_STEP_DELAY = max(0.0005, float(os.getenv("WIRE_MOTOR_STEP_DELAY", "0.001")))
MOTOR_MAX_RUN_SECONDS = max(0.5, float(os.getenv("WIRE_MOTOR_MAX_RUN_SECONDS", "10")))
MACHINE_MIN = max(1, int(os.getenv("WIRE_MACHINE_MIN", "100")))
MACHINE_MAX = max(MACHINE_MIN, int(os.getenv("WIRE_MACHINE_MAX", "999")))
MACHINE_STATE_FILE = INSPECTION_DIR / "machine_state.json"
MACHINE_BUTTONS_ENABLED = os.getenv("WIRE_MACHINE_BUTTONS_ENABLED", "0").strip().lower() not in {"0", "false", "no", "off"}
MACHINE_PLUS_BUTTON_PIN = int(os.getenv("WIRE_MACHINE_PLUS_GPIO", "14"))
MACHINE_MINUS_BUTTON_PIN = int(os.getenv("WIRE_MACHINE_MINUS_GPIO", "15"))
LOG_FILE = INSPECTION_DIR / "inspection_log.jsonl"
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

if (APP_DIR / "frontend").exists():
    app.mount("/ui", StaticFiles(directory=str(APP_DIR / "frontend"), html=True), name="frontend")


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


def predict_image(
    img: Image.Image,
    processing: Optional[dict] = None,
    stem: str = "inspection",
    machine_number: Optional[int] = None,
):
    processed_img, processing_settings = prepare_image_for_model(img, processing)
    images = image_store.save(img, processed_img, stem, machine_number=machine_number)
    # Read the saved model variant, so its pixels are the actual inference input.
    img = open_image_from_path(Path(images["224x224"]["path"]))

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

    result = {
        "prediction": prediction,
        "confidence": round(confidence, 2),
        "raw_score": round(score, 4),
        "processing": processing_settings,
        "images": images,
        "machine_number": machine_number if machine_number is not None else MACHINE_MIN,
    }
    if any(processing_settings.values()):
        result["processed_path"] = images["224x224"]["path"]
    return result


def warm_up_model():
    dummy = np.zeros((1, IMG_SIZE, IMG_SIZE, 3), dtype=np.float32)
    try:
        model.predict(dummy, verbose=0)
        print("SurfaceAI model loaded and warm-up prediction passed", flush=True)
        return None
    except Exception as exc:
        error = f"Model warm-up prediction failed: {exc}"
        print(error, flush=True)
        return error


MODEL_WARMUP_ERROR = warm_up_model()


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
        "machine_number": result.get("machine_number", MACHINE_MIN),
        "processing": result.get("processing", {}),
        "images": result.get("images", {}),
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

    def capture_image(self) -> Image.Image:
        self.start()
        with self.lock:
            still_config = self._create_camera_config(self.picam2, "still")
            image_array = self.picam2.switch_mode_and_capture_array(still_config)

        if image_array.ndim == 3 and image_array.shape[2] == 4:
            image_array = image_array[:, :, :3]

        actual_size = (int(image_array.shape[1]), int(image_array.shape[0]))
        if actual_size != self.still_size:
            raise RuntimeError(
                f"Camera returned {actual_size[0]}x{actual_size[1]}; "
                f"expected {self.still_size[0]}x{self.still_size[1]}. Image was not saved."
            )

        return Image.fromarray(image_array).convert("RGB")


camera_manager = CameraManager()
inspection_capture_lock = threading.Lock()


class MachineCounter:
    """Thread-safe, persistent source-machine selector."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._lock = threading.Lock()
        self._value = MACHINE_MIN
        self._load()

    def _load(self):
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self._value = max(MACHINE_MIN, min(MACHINE_MAX, int(data["machine_number"])))
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._value = MACHINE_MIN

    def _save_locked(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"machine_number": self._value}) + "\n", encoding="utf-8")
        temporary.replace(self.state_file)

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def set(self, value: int) -> int:
        with self._lock:
            self._value = max(MACHINE_MIN, min(MACHINE_MAX, int(value)))
            self._save_locked()
            return self._value

    def adjust(self, delta: int) -> int:
        with self._lock:
            self._value = max(MACHINE_MIN, min(MACHINE_MAX, self._value + delta))
            self._save_locked()
            return self._value


machine_counter = MachineCounter(MACHINE_STATE_FILE)


def resolve_image_path(path_value: str) -> Path:
    if not path_value:
        raise HTTPException(status_code=400, detail="Missing image path")

    requested = Path(path_value).expanduser()
    if not requested.is_absolute():
        # Keep old relative paths usable; bare new filenames resolve to evidence.
        candidates = [IMAGE_ROOT / requested, CAPTURE_DIR / requested]
        requested = next((p for p in candidates if p.is_file()), candidates[0])

    resolved = requested.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found: {path_value}")

    if resolved.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    return resolved


def capture_and_inspect(processing: Optional[dict] = None) -> dict:
    """Capture a still, run the model, and record the inspection."""
    # Touchscreen and GPIO requests share one physical camera and one model.
    # Queue simultaneous requests instead of allowing their operations to race.
    with inspection_capture_lock:
        machine_number = machine_counter.value
        img = camera_manager.capture_image()
        processing = processing or build_processing_settings()
        result = predict_image(img, processing, "capture", machine_number=machine_number)
        image_path = result["images"]["1600x1200"]["path"]
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
                started_at = (self.last_event or {}).get("started_at")
                self.last_event = {
                    "id": event_id,
                    "state": "complete",
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "result": result,
                }
            print(f"Hardware capture complete: {result['path']}", flush=True)
        except Exception as exc:
            self.last_error = str(exc)
            with self._event_lock:
                started_at = (self.last_event or {}).get("started_at")
                self.last_event = {
                    "id": event_id,
                    "state": "failed",
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                }
            print(f"Hardware capture failed: {exc}", flush=True)
        finally:
            self._capture_lock.release()

    def status(self) -> dict:
        with self._event_lock:
            event = dict(self.last_event) if self.last_event else None
        return {"enabled": GPIO_BUTTON_ENABLED, "available": self.button is not None, "pin": self.pin, "physical_pin": 16, "last_event": event, "error": self.last_error}

    def stop(self):
        if self.button is None:
            return
        try:
            self.button.close()
        finally:
            self.button = None


class LeadScrewController:
    """Drive the M2 stepper while either physical direction button is held."""

    def __init__(self):
        self.up_button = None
        self.down_button = None
        self.enable = None
        self.step = None
        self.direction = None
        self.last_error = None
        self.state = "disabled" if not MOTOR_ENABLED else "starting"
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        if not MOTOR_ENABLED:
            print("Lead-screw motor disabled by WIRE_MOTOR_ENABLED", flush=True)
            return
        if platform.system() != "Linux":
            self.state = "unavailable"
            print("Lead-screw motor is only available on Raspberry Pi/Linux", flush=True)
            return
        try:
            from gpiozero import Button, OutputDevice

            self.up_button = Button(MOTOR_UP_BUTTON_PIN, pull_up=True, bounce_time=0.03)
            self.down_button = Button(MOTOR_DOWN_BUTTON_PIN, pull_up=True, bounce_time=0.03)
            # This Stepper Motor HAT revision enables M2 with a HIGH signal.
            self.enable = OutputDevice(MOTOR_ENABLE_PIN, initial_value=False)
            self.step = OutputDevice(MOTOR_STEP_PIN, initial_value=False)
            self.direction = OutputDevice(MOTOR_DIRECTION_PIN, initial_value=False)
            self._stop_event.clear()
            self.state = "idle"
            self._thread = threading.Thread(target=self._run, name="lead-screw-m2", daemon=True)
            self._thread.start()
            print(
                "Lead-screw motor ready: UP GPIO5, DOWN GPIO25, "
                "M2 ENABLE/STEP/DIR GPIO4/GPIO18/GPIO24",
                flush=True,
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.state = "unavailable"
            self._close_devices()
            print(f"Lead-screw motor unavailable: {exc}", flush=True)

    def _run(self):
        active_direction = None
        movement_started = None
        try:
            while not self._stop_event.is_set():
                up_pressed = self.up_button.is_pressed
                down_pressed = self.down_button.is_pressed
                requested_direction = (
                    "up" if up_pressed and not down_pressed
                    else "down" if down_pressed and not up_pressed
                    else None
                )

                if requested_direction is None:
                    self._disable_motor("idle")
                    active_direction = None
                    movement_started = None
                    self._stop_event.wait(0.005)
                    continue

                if requested_direction != active_direction:
                    active_direction = requested_direction
                    movement_started = time.monotonic()
                    self.direction.value = 0 if requested_direction == "up" else 1
                    self.enable.on()
                    self.state = requested_direction

                if time.monotonic() - movement_started >= MOTOR_MAX_RUN_SECONDS:
                    self._disable_motor("safety-stop")
                    # Require release before another movement can begin.
                    while not self._stop_event.is_set() and (
                        self.up_button.is_pressed or self.down_button.is_pressed
                    ):
                        self._stop_event.wait(0.02)
                    active_direction = None
                    movement_started = None
                    continue

                self.step.on()
                time.sleep(MOTOR_STEP_DELAY)
                self.step.off()
                time.sleep(MOTOR_STEP_DELAY)
        except Exception as exc:
            self.last_error = str(exc)
            self.state = "failed"
            print(f"Lead-screw motor stopped after GPIO error: {exc}", flush=True)
        finally:
            self._disable_motor("stopped")

    def _disable_motor(self, state):
        if self.step is not None:
            self.step.off()
        if self.enable is not None:
            self.enable.off()
        self.state = state

    def status(self) -> dict:
        return {
            "enabled": MOTOR_ENABLED,
            "available": self._thread is not None and self._thread.is_alive(),
            "state": self.state,
            "up_button_gpio": MOTOR_UP_BUTTON_PIN,
            "down_button_gpio": MOTOR_DOWN_BUTTON_PIN,
            "m2": {
                "enable_gpio": MOTOR_ENABLE_PIN,
                "step_gpio": MOTOR_STEP_PIN,
                "direction_gpio": MOTOR_DIRECTION_PIN,
            },
            "max_run_seconds": MOTOR_MAX_RUN_SECONDS,
            "error": self.last_error,
        }

    def _close_devices(self):
        for device_name in ("up_button", "down_button", "step", "direction", "enable"):
            device = getattr(self, device_name)
            if device is not None:
                try:
                    device.close()
                finally:
                    setattr(self, device_name, None)

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        self._disable_motor("stopped")
        self._close_devices()


class MachineCounterButtons:
    """Optional physical buttons for changing the selected machine number."""

    def __init__(self):
        self.plus_button = None
        self.minus_button = None
        self.last_error = None

    def start(self):
        if not MACHINE_BUTTONS_ENABLED:
            print("Machine counter GPIO buttons disabled until their pins are verified", flush=True)
            return
        if platform.system() != "Linux":
            return
        try:
            from gpiozero import Button

            self.plus_button = Button(MACHINE_PLUS_BUTTON_PIN, pull_up=True, bounce_time=0.12)
            self.minus_button = Button(MACHINE_MINUS_BUTTON_PIN, pull_up=True, bounce_time=0.12)
            self.plus_button.when_pressed = lambda: self._adjust(1)
            self.minus_button.when_pressed = lambda: self._adjust(-1)
            print(
                f"Machine counter buttons ready: + GPIO{MACHINE_PLUS_BUTTON_PIN}, "
                f"- GPIO{MACHINE_MINUS_BUTTON_PIN}",
                flush=True,
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.stop()
            print(f"Machine counter buttons unavailable: {exc}", flush=True)

    def _adjust(self, delta: int):
        value = machine_counter.adjust(delta)
        print(f"Selected source machine: {value}", flush=True)

    def status(self) -> dict:
        return {
            "enabled": MACHINE_BUTTONS_ENABLED,
            "available": self.plus_button is not None and self.minus_button is not None,
            "plus_gpio": MACHINE_PLUS_BUTTON_PIN,
            "minus_gpio": MACHINE_MINUS_BUTTON_PIN,
            "error": self.last_error,
        }

    def stop(self):
        for name in ("plus_button", "minus_button"):
            button = getattr(self, name)
            if button is not None:
                try:
                    button.close()
                finally:
                    setattr(self, name, None)


hardware_capture_button = HardwareCaptureButton(GPIO_BUTTON_PIN)
hardware_capture_button.start()
lead_screw_controller = LeadScrewController()
lead_screw_controller.start()
machine_counter_buttons = MachineCounterButtons()
machine_counter_buttons.start()


@app.on_event("shutdown")
def shutdown_hardware():
    """Release camera and GPIO resources during a controlled server shutdown."""
    machine_counter_buttons.stop()
    lead_screw_controller.stop()
    hardware_capture_button.stop()
    camera_manager.stop()


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
    if (APP_DIR / "frontend/index.html").exists():
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
        "model_loaded": model is not None,
        "model_ready": model is not None and MODEL_WARMUP_ERROR is None,
        "model_error": MODEL_WARMUP_ERROR,
        "api_connected": True,
        "device": platform.machine(),
        "platform": platform.platform(),
        "tensorflow_version": tf.__version__,
        "gpu_available": bool(tf.config.list_physical_devices("GPU")),
        "image_root": str(IMAGE_ROOT),
        "image_directories": {key: str(IMAGE_ROOT / key) for key in IMAGE_SIZES},
        "inspection_dir": str(INSPECTION_DIR),
        "capture_dir": str(CAPTURE_DIR),
        "camera": camera_manager.status(),
        "stream_fps": STREAM_FPS,
        "stream_jpeg_quality": STREAM_JPEG_QUALITY,
        "capture_mode": CAPTURE_MODE,
        "hardware_button": hardware_capture_button.status(),
        "lead_screw": lead_screw_controller.status(),
        "machine": {
            "number": machine_counter.value,
            "minimum": MACHINE_MIN,
            "maximum": MACHINE_MAX,
            "buttons": machine_counter_buttons.status(),
        },
        "ui_available": (APP_DIR / "frontend/index.html").exists(),
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
    processing = build_processing_settings(brightness, contrast, sharpness, mask_strength)
    machine_number = machine_counter.value
    result = predict_image(
        img, processing, Path(file.filename or "upload").stem,
        machine_number=machine_number,
    )
    result["source"] = "upload"
    result["filename"] = file.filename
    result["saved_path"] = result["images"]["1600x1200"]["path"]
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
    machine_number = machine_counter.value
    result = predict_image(img, processing, image_path.stem, machine_number=machine_number)
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
    # Camera capture and TensorFlow inference are synchronous and can take several
    # seconds on a Raspberry Pi. Keep them off the ASGI event loop so status and
    # hardware-button polling remain responsive while a touchscreen capture runs.
    return await run_in_threadpool(capture_and_inspect, processing)


@app.get("/hardware-button/status")
async def hardware_button_status(after: Optional[str] = None):
    status = hardware_capture_button.status()
    event = status.get("last_event")
    if after and event and event.get("id") == after:
        # The browser already consumed this result. Avoid retransmitting and
        # parsing the full prediction/log payload on every status poll.
        status["unchanged"] = True
        status["last_event"] = {
            key: event.get(key)
            for key in ("id", "state", "started_at", "completed_at")
            if event.get(key) is not None
        }
    else:
        status["unchanged"] = False
    return status


@app.get("/motor/status")
async def motor_status():
    return lead_screw_controller.status()


@app.get("/machine")
async def machine_status():
    return {
        "machine_number": machine_counter.value,
        "minimum": MACHINE_MIN,
        "maximum": MACHINE_MAX,
        "buttons": machine_counter_buttons.status(),
    }


@app.post("/machine/increment")
async def increment_machine():
    return {"machine_number": machine_counter.adjust(1)}


@app.post("/machine/decrement")
async def decrement_machine():
    return {"machine_number": machine_counter.adjust(-1)}


@app.post("/machine/{number}")
async def set_machine(number: int):
    if not MACHINE_MIN <= number <= MACHINE_MAX:
        raise HTTPException(status_code=400, detail=f"Machine number must be {MACHINE_MIN}-{MACHINE_MAX}")
    return {"machine_number": machine_counter.set(number)}


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


@app.get("/images/{resolution}/{filename}")
async def stored_image(resolution: str, filename: str):
    try:
        path = image_store.resolve_served_image(resolution, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Image not found") from exc
    return FileResponse(path)
