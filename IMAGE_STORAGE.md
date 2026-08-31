# Inspection image storage

All runtime inspection images now use one store, defaulting to `images/` beside
`app.py`. It is created automatically, including the three resolution folders:

```text
images/
├── 1600x1200/
├── 640x320/
└── 224x224/
```

| Folder | Content and consumer |
| --- | --- |
| `1600x1200` | RGB evidence before tuning; full-resolution evidence link |
| `640x320` | Tuned RGB preview; dashboard display |
| `224x224` | Tuned RGB input; reopened from disk for MobileNetV2 inference |

Each completed inspection produces one uniquely named PNG in each folder. All
three share a filename. PNG avoids adding JPEG compression to the model input,
but uses more disk space than the previous JPEG capture files. There is no
automatic retention/deletion policy; monitor the Pi's available disk space.

Evidence and preview use aspect-preserving fitting with black padding, never
cropping. Non-1600x1200 uploads are resized, so the evidence copy is not a
byte-for-byte archive of an arbitrary original upload. Camera stills must actually
be 1600x1200 or capture fails without saving a lower-resolution substitute.
Model input keeps the previous direct bicubic resize to 224x224 (without padding),
enhancements, background suppression, and MobileNetV2 normalization. The saved
PNG contains the pixels before normalization, not floating-point model tensors.

## What changed, and what is preserved

| Previous storage | New behavior |
| --- | --- |
| `inspection_data/uploads/` | All upload inspections save the three variants |
| `inspection_data/processed/` | Preview and model folders hold the tuned images |
| `~/Desktop/CapturedImages` / `WIRE_CAPTURE_DIR` | Camera and GPIO captures use the shared store |
| In-memory-only 224x224 image | Model reads the losslessly saved 224x224 variant |
| Relative images under `WIRE_IMAGE_ROOT` | Still readable; new resolution folders live inside this root |
| `inspection_data/inspection_log.jsonl` | Kept; new records also link variants and settings |
| Browser session counters/history | Still in memory; this change does not add browser persistence |
| CSV/PDF exports | Continue downloading to the browser's download location |
| Training/evaluation `dataset/` and `.keras` files | Unchanged: these are training data/model artifacts, not runtime inspection storage |
| Temporary model archive extraction | Unchanged; temporary loading files are cleaned automatically |

Live MJPEG frames remain in memory and are not archived frame by frame. The
camera's preview configuration remains 640x480 by default, independent of the
fixed 640x320 **saved** preview. Live streaming remains live after an inspection;
saved-preview and evidence links appear below the verdict. Uploaded and
stored-path results also show their saved preview when the live stream is off.

The unresolved merge markers found in `app.py` and `RASPBERRY_PI_SETUP.md` were
resolved in favor of the fixed 1600x1200 still-capture workflow.

## Configuration and old images

Set `WIRE_IMAGE_ROOT` to relocate the whole image store. Relative configuration
paths resolve beside `app.py`, so launching from a different directory does not
silently select different storage. Use absolute paths for an external drive.

```bash
export WIRE_IMAGE_ROOT=/home/pi/wire_images
uvicorn app:app --host 0.0.0.0 --port 8000
```

Remove `WIRE_CAPTURE_DIR` from custom launcher configuration; it is no longer a
separate destination. `WIRE_INSPECTION_DIR` continues to control the history
directory. No existing files are removed or automatically migrated. Inspect an
old absolute image path to create its three new variants. Legacy relative paths
under `WIRE_IMAGE_ROOT` remain supported. A bare newly generated filename resolves
to `1600x1200/<filename>`; explicit resolution-relative paths also work.

Do not point `Inspect Path` at a tuned model/preview image unless you intentionally
want to inspect those already-processed pixels again. Use the evidence path when
changing tuning settings. Old log entries are kept as recorded; new inspections
append new records with the new paths. Reinspection creates a new bundle so
previous evidence and processing results are never overwritten.

## API compatibility

Existing route names, input fields, prediction/confidence fields, and processing
parameters are unchanged:

- `POST /predict` still accepts multipart `file` and tuning form fields; `filename`
  retains the uploaded name and `saved_path` now identifies the 1600x1200 PNG.
- `POST /predict-path?path=...` still accepts stored paths and returns the original
  `path`. Its new bundle's evidence is available through `images["1600x1200"]`.
- `POST /capture` and GPIO capture still return `path`, now the evidence PNG.
- `processed_path`, when tuning is nonzero, now identifies the saved 224x224 model
  input instead of a separate arbitrary-size processed JPEG.
- Every inspection response includes `images`, keyed by the three resolution
  names, each with `path`, `url`, `width`, and `height`.
- `GET /images/{resolution}/{filename}` serves stored images, restricting retrieval
  to supported resolution directories and rejecting symlink/path escapes.
- `GET /status` retains its existing fields and adds `image_directories`.
- `/history`, `/camera/status`, `/camera/stream`, `/camera/stop`,
  `/hardware-button/status`, `/api`, `/`, and `/ui/` remain available.

Image URLs are relative to the API server, not local `file://` URLs. The frontend
uses its configured API base for them. Existing API authentication/network-access
behavior is unchanged; anyone who can access the API and knows an image URL can
retrieve that image. Restrict access to the intended inspection network.

## Verification

With the app dependencies installed:

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q tests
node --check frontend/script.js
node tests/test_frontend_storage.cjs
```

The tests use real FastAPI requests, Pillow image encoding/decoding, and file
storage. TensorFlow prediction and camera hardware are substitutes: these tests
verify API contracts and exact model-input pixels, not model accuracy or hardware
operation. Before production use on the Pi, run an upload, a stored-path
inspection, an on-screen capture, and a GPIO-button capture with the real model;
check all three files, the displayed evidence/preview, and live-stream recovery.
