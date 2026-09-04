import os
import sys
import io
import base64
from pathlib import Path
from typing import Optional

# Ensure KERAS_HOME is set within workspace to prevent sandbox permission errors
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("KERAS_HOME", os.path.join(WORKSPACE_DIR, ".keras"))

import numpy as np
from PIL import Image
from pydantic import BaseModel

import tensorflow as tf
from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(
    title="Wire Defect Detection API",
    description="Real-time Wire Defect Inspection with MobileNetV2",
    version="2.0.0"
)

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

IMG_SIZE = 224
MODEL_PATH = os.path.join(WORKSPACE_DIR, "best_wire_model.keras")

# Load model safely
model = None
try:
    if os.path.exists(MODEL_PATH):
        model = tf.keras.models.load_model(MODEL_PATH, compile=False)
        print(f"[*] Successfully loaded model from {MODEL_PATH}")
    else:
        alt_models = list(Path(WORKSPACE_DIR).glob("*.keras"))
        if alt_models:
            model = tf.keras.models.load_model(str(alt_models[0]), compile=False)
            print(f"[*] Loaded fallback model from {alt_models[0]}")
        else:
            print(f"[!] Warning: No .keras model found in {WORKSPACE_DIR}")
except Exception as e:
    print(f"[!] Error loading model: {e}")


def run_inference(img: Image.Image):
    """Preprocess PIL Image and run model prediction."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model is not loaded on the server.")

    img_rgb = img.convert("RGB").resize((IMG_SIZE, IMG_SIZE))
    img_array = image.img_to_array(img_rgb)
    img_array = np.expand_dims(img_array, axis=0)
    img_array = preprocess_input(img_array)

    pred = model.predict(img_array, verbose=0)
    score = float(pred[0][0])

    # 0 = defected_wire, 1 = ok_wire
    if score >= 0.5:
        prediction = "ok_wire"
        verdict = "PASS"
        confidence = score * 100.0
    else:
        prediction = "defected_wire"
        verdict = "REJECT"
        confidence = (1.0 - score) * 100.0

    return {
        "prediction": prediction,
        "verdict": verdict,
        "confidence": round(confidence, 2),
        "raw_score": round(score, 4),
        "good_score": round(score * 100.0, 2),
        "defect_score": round((1.0 - score) * 100.0, 2),
    }


class Base64ImagePayload(BaseModel):
    image: str
    brightness: Optional[int] = 0
    contrast: Optional[int] = 0
    sharpness: Optional[int] = 0


@app.get("/status")
async def get_status():
    """Return system, GPU, and model status."""
    gpu_devices = tf.config.list_physical_devices("GPU")
    device_name = "Apple Silicon Metal GPU" if gpu_devices else "CPU"

    return {
        "model_name": "MobileNetV2",
        "model_loaded": model is not None,
        "api_connected": True,
        "gpu_available": len(gpu_devices) > 0,
        "gpu_device_count": len(gpu_devices),
        "device": device_name,
        "input_resolution": f"{IMG_SIZE}x{IMG_SIZE}",
        "classes": ["defected_wire", "ok_wire"]
    }


@app.get("/health")
async def health_check():
    return {"status": "ok", "model_ready": model is not None}


@app.post("/predict")
async def predict_upload(file: UploadFile = File(...)):
    """Predict defect on an uploaded image file."""
    try:
        contents = await file.read()
        pil_img = Image.open(io.BytesIO(contents))
        result = run_inference(pil_img)
        result["filename"] = file.filename
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process image: {str(e)}")


@app.post("/predict-base64")
async def predict_base64(payload: Base64ImagePayload):
    """Predict defect on a Base64-encoded image string from webcam/canvas."""
    try:
        data = payload.image
        if "," in data:
            data = data.split(",", 1)[1]

        image_bytes = base64.b64decode(data)
        pil_img = Image.open(io.BytesIO(image_bytes))
        result = run_inference(pil_img)
        result["source"] = "webcam_capture"
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process Base64 image: {str(e)}")


# Serve frontend static assets
FRONTEND_DIR = os.path.join(WORKSPACE_DIR, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))