import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    accuracy_score
)

import numpy as np

IMG_SIZE = 224
BATCH_SIZE = 16

# Load best model
model = tf.keras.models.load_model(
    "best_wire_model.keras",
    compile=False
)

# Test dataset
test_datagen = ImageDataGenerator(
    preprocessing_function=preprocess_input
)

test_data = test_datagen.flow_from_directory(
    "dataset/test",
    target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE,
    class_mode="binary",
    shuffle=False
)

# Predictions
pred_probs = model.predict(test_data)

predictions = (pred_probs > 0.5).astype(int).flatten()

true_labels = test_data.classes

# Accuracy
acc = accuracy_score(
    true_labels,
    predictions
)

print("\n========================")
print(f"Test Accuracy: {acc*100:.2f}%")
print("========================\n")

# Classification Report
print(
    classification_report(
        true_labels,
        predictions,
        target_names=list(test_data.class_indices.keys())
    )
)

# Confusion Matrix
cm = confusion_matrix(
    true_labels,
    predictions
)

print("\nConfusion Matrix:\n")
print(cm)

print("\nClass Mapping:")
print(test_data.class_indices)