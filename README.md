# Wire Defect Detection using Transfer Learning

## Overview

Wire Defect Detection is a computer vision system developed to automatically classify microscope images of industrial wire surfaces into:

- Defected Wire
- OK Wire

The system uses Transfer Learning with MobileNetV2 and provides real-time predictions through a FastAPI backend and a web-based frontend.

---

## Performance Highlights

- Test Accuracy: **94.74%**
- Precision: **94%**
- Recall: **94%**
- F1 Score: **94%**
- Evaluated on **114 completely unseen test images**
- Powered by **MobileNetV2 Transfer Learning**

---

## Features

- Binary classification of industrial wire images
- Transfer Learning using MobileNetV2
- FastAPI backend for real-time inference
- Interactive web interface
- GPU-accelerated training using Apple Silicon (TensorFlow Metal)
- Real-time confidence scores
- Model evaluation using confusion matrix and classification metrics
- Optimized for industrial quality inspection

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
| Total | 753 |

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

- Frozen feature extraction layers
- Custom classification head
- Global Average Pooling Layer
- Dense Layer (64 units)
- Dropout Regularization
- Binary Classification Output Layer

### Input Size

224 × 224 RGB Images

---

## Training Configuration

| Parameter | Value |
|------------|--------|
| Epochs | 25 |
| Batch Size | 16 |
| Optimizer | Adam |
| Loss Function | Binary Cross Entropy |
| Base Model | MobileNetV2 |
| Device | Apple M3 Max GPU |
| Framework | TensorFlow 2.15 |
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
| Accuracy | 95.58% |

### Test Results (Unseen Images)

| Metric | Score |
|----------|---------:|
| Accuracy | 94.74% |
| Precision | 94% |
| Recall | 94% |
| F1 Score | 94% |

### Confusion Matrix

| Actual / Predicted | Defected | OK Wire |
|--------------------|---------:|---------:|
| Defected | 51 | 3 |
| OK Wire | 3 | 57 |

### Summary

- Total Test Images: 114
- Correct Predictions: 108
- Incorrect Predictions: 6
- Overall Accuracy: 94.74%

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

macOS/Linux:

```bash
source venv/bin/activate
```

Windows:

```bash
venv\Scripts\activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Training

```bash
python train_model.py
```

The trained model will be saved as:

```text
best_wire_model.keras
```

---

## Evaluation

```bash
python evaluate_model.py
```

This generates:

- Accuracy
- Precision
- Recall
- F1 Score
- Confusion Matrix

---

## Run API Server

```bash
uvicorn app:app --reload
```

API URL:

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

Input:

- Image File

Output:

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
- NumPy
- Pillow
- Scikit-learn
- HTML
- CSS
- JavaScript

---

## Future Improvements

- Larger industrial dataset collection
- Multi-class defect classification
- Defect localization using Object Detection
- Defect segmentation using U-Net
- Raspberry Pi deployment
- Real-time factory integration
- Edge AI optimization

---

## Author

**Tanishq Jadhav**

B.Tech Student (Artificial Intelligence & Machine Learning)

Project: Wire Defect Detection using Transfer Learning

---

## License

This project is intended for educational, research, and industrial quality inspection purposes.