from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

import tensorflow as tf
from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

import numpy as np
from PIL import Image
import io

app = FastAPI()

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

@app.get("/")
async def root():
    return {
        "message": "Wire Defect Detection API Running"
    }

@app.get("/status")
async def status():
    return {
        "model_name": "MobileNetV2",
        "model_loaded": True,
        "api_connected": True
    }

@app.post("/predict")
async def predict(file: UploadFile = File(...)):

    contents = await file.read()

    # Read image
    img = Image.open(io.BytesIO(contents)).convert("RGB")
    img = img.resize((IMG_SIZE, IMG_SIZE))

    # Preprocess image (MUST MATCH TRAINING)
    img_array = image.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)
    img_array = preprocess_input(img_array)

    # Predict
    pred = model.predict(img_array, verbose=0)

    score = float(pred[0][0])

    # Current assumption:
    # defected = 0
    # ok_wire = 1

    if score >= 0.5:
        prediction = "ok_wire"
        confidence = score * 100
    else:
        prediction = "defected_wire"
        confidence = (1 - score) * 100

    return {
        "prediction": prediction,
        "confidence": round(confidence, 2),
        "raw_score": round(score, 4)
    }