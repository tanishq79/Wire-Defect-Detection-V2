# Wire Defect Detection (Version 2)

## Overview

Wire Defect Detection V2 is a deep learning-based computer vision system designed to automatically inspect industrial wire surface images and classify them into two categories:

- Defected Wire
- OK Wire

The system leverages Transfer Learning with MobileNetV2 to achieve high classification accuracy while reducing training time. It provides real-time predictions through a FastAPI backend and an interactive web-based frontend, making it suitable for industrial quality inspection applications.

---

## Performance Highlights

- Test Accuracy: **94.74%**
- Validation Accuracy: **95.58%**
- Precision: **94%**
- Recall: **94%**
- F1 Score: **94%**
- Evaluated on **114 unseen test images**
- Powered by **MobileNetV2 Transfer Learning**

---

## Features

- Binary classification of industrial wire images
- Transfer Learning using MobileNetV2
- FastAPI REST API for real-time inference
- Interactive web interface
- GPU-accelerated training using Apple Silicon (TensorFlow Metal)
- Real-time confidence score prediction
- Confusion Matrix and Classification Report generation
- Optimized for industrial wire quality inspection

---

## Dataset

The dataset consists of microscope images captured from industrial wire surfaces.

### Classes

- Defected
- OK_Wire

### Dataset Distribution

| Split | Images |
|--------|--------:|
| Training | 526 |
| Validation | 113 |
| Testing | 114 |
| **Total** | **753** |

### Class Distribution

| Class | Images |
|--------|--------:|
| Defected | 358 |
| OK_Wire | 395 |

---

## Model Architecture

### Base Model

- MobileNetV2 (Pretrained on ImageNet)

### Transfer Learning Strategy

- Frozen MobileNetV2 feature extraction layers
- Global Average Pooling Layer
- Dense Layer (64 Units, ReLU)
- Dropout Layer
- Binary Classification Output Layer (Sigmoid)

### Input Size

- **224 × 224 RGB Images**

---

## Training Configuration

| Parameter | Value |
|------------|--------|
| Base Model | MobileNetV2 |
| Epochs | 25 |
| Batch Size | 16 |
| Optimizer | Adam |
| Loss Function | Binary Cross Entropy |
| Framework | TensorFlow 2.15 |
| Device | Apple M3 Max GPU |
| Image Size | 224 × 224 |

### Data Augmentation

- Random Horizontal Flip
- Random Rotation
- Random Zoom

---

## Performance

### Validation Results

| Metric | Score |
|----------|---------:|
| Accuracy | **95.58%** |

### Test Results

| Metric | Score |
|----------|---------:|
| Accuracy | **94.74%** |
| Precision | **94%** |
| Recall | **94%** |
| F1 Score | **94%** |

### Confusion Matrix

| Actual / Predicted | Defected | OK Wire |
|--------------------|---------:|---------:|
| Defected | 51 | 3 |
| OK Wire | 3 | 57 |

### Summary

- Total Test Images: **114**
- Correct Predictions: **108**
- Incorrect Predictions: **6**
- Overall Accuracy: **94.74%**

---

## Project Structure

```text
Wire_Defect_Detection_V2/
│
├── app.py
├── train_model.py
├── evaluate_model.py
├── split_dataset.py
├── requirements.txt
├── .gitignore
│
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── script.js
│
├── dataset/
│   ├── train/
│   ├── val/
│   └── test/
│
└── best_wire_model.keras
```

---

## Installation

### Clone Repository

```bash
git clone https://github.com/tanishq79/Wire-Defect-Detection-V2.git
cd Wire_Defect_Detection_V2
```

### Create Virtual Environment

```bash
python3.10 -m venv venv
```

### Activate Environment

**macOS / Linux**

```bash
source venv/bin/activate
```

**Windows**

```bash
venv\Scripts\activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Verify Environment

Before running the project, verify that the required software versions are correctly installed.

### Check Python Version

```bash
python --version
```

Expected Output:

```text
Python 3.10.x
```

### Check TensorFlow Version

```python
import tensorflow as tf

print(tf.__version__)
```

Expected Output:

```text
2.15.0
```

### Check FastAPI Version

```bash
python -c "import fastapi; print(fastapi.__version__)"
```

### Check NumPy Version

```bash
python -c "import numpy; print(numpy.__version__)"
```

---

## Development Environment

The project was developed and tested using the following environment.

| Software | Version |
|----------|---------|
| Python | 3.10.x |
| TensorFlow | 2.15.0 |
| TensorFlow Metal | Latest Compatible |
| FastAPI | Latest Compatible |
| Uvicorn | Latest Compatible |
| NumPy | Latest Compatible |
| Pillow | Latest Compatible |
| Scikit-learn | Latest Compatible |
| Operating System | macOS (Apple Silicon) |

---

## Training

Train the model using:

```bash
python train_model.py
```

The trained model will be saved as:

```text
best_wire_model.keras
```

---

## Evaluation

Evaluate the trained model using:

```bash
python evaluate_model.py
```

This generates:

- Accuracy
- Precision
- Recall
- F1 Score
- Confusion Matrix
- Classification Report

---

## Running the API

Runtime inspection images use one main `images/` folder containing `1600x1200/`,
`640x320/`, and `224x224/`. Upload, stored-path, camera, and GPIO inspections all
save linked variants there. See [Image storage and compatibility](IMAGE_STORAGE.md)
for configuration, existing-data handling, and API details.

Start the FastAPI server:

```bash
uvicorn app:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

---

## API Endpoints

### Health Check

```http
GET /status
```

### Predict Wire Condition

```http
POST /predict
```

**Input**

- Image File

**Sample Response**

```json
{
  "prediction": "defected_wire",
  "confidence": 98.45
}
```

---

## Technologies Used

- Python
- TensorFlow
- TensorFlow Metal
- MobileNetV2
- FastAPI
- Uvicorn
- NumPy
- Pillow
- Scikit-learn
- HTML
- CSS
- JavaScript

---

## Future Improvements

- Expand the industrial dataset
- Multi-class defect classification
- Object detection for defect localization
- Semantic segmentation using U-Net
- Raspberry Pi deployment
- Edge AI optimization
- Real-time industrial production line integration

---

## Author

**Tanishq Jadhav**

B.Tech – Computer Science Engineering (Artificial Intelligence & Machine Learning)

**Project:** Wire Defect Detection using Transfer Learning (Version 2)

---

## License

This project is intended for educational, research, and industrial quality inspection purposes.
