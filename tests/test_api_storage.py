"""Real FastAPI/Pillow requests, with deterministic model/camera substitutes.

These test storage and API contracts, not TensorFlow accuracy or Pi hardware.
"""
import importlib
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
from PIL import Image
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("WIRE_IMAGE_ROOT", str(tmp_path / "images"))
    monkeypatch.setenv("WIRE_INSPECTION_DIR", str(tmp_path / "records"))
    monkeypatch.setenv("WIRE_CAPTURE_DIR", str(tmp_path / "obsolete_captures"))
    monkeypatch.setenv("WIRE_BUTTON_ENABLED", "0")

    class FakeModel:
        last_input = None

        def predict(self, array, verbose=0):
            self.last_input = array.copy()
            return np.array([[0.8]])

    class Depthwise:
        @classmethod
        def from_config(cls, config):
            return config

    model = FakeModel()
    modules = {name: ModuleType(name) for name in [
        "tensorflow", "tensorflow.keras", "tensorflow.keras.preprocessing",
        "tensorflow.keras.applications", "tensorflow.keras.applications.mobilenet_v2",
    ]}
    tf = modules["tensorflow"]
    tf.__version__ = "test-double"
    tf.keras = SimpleNamespace(layers=SimpleNamespace(DepthwiseConv2D=Depthwise),
                               models=SimpleNamespace(load_model=lambda *a, **k: model))
    tf.config = SimpleNamespace(list_physical_devices=lambda kind: [])
    modules["tensorflow.keras.preprocessing"].image = SimpleNamespace(img_to_array=lambda img: np.asarray(img, dtype=np.float32))
    modules["tensorflow.keras.applications.mobilenet_v2"].preprocess_input = lambda arr: arr / 127.5 - 1
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    with TestClient(module.app) as client:
        yield module, client, model
    sys.modules.pop("app", None)


def image_bytes(size=(301, 157)):
    image = Image.fromarray(np.random.default_rng(42).integers(0, 256, (*size[::-1], 3), dtype=np.uint8))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def assert_bundle(client, result):
    assert set(result["images"]) == {"1600x1200", "640x320", "224x224"}
    filenames = set()
    for resolution, metadata in result["images"].items():
        response = client.get(metadata["url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(response.content)) as img:
            assert img.size == tuple(map(int, resolution.split("x")))
        filenames.add(Path(metadata["path"]).name)
    assert len(filenames) == 1


@pytest.mark.parametrize("processing", [{}, {"brightness": 25, "contrast": -10, "sharpness": 30, "mask_strength": 20}])
def test_upload_contract_and_exact_model_input(api, processing):
    module, client, model = api
    contents = image_bytes()
    response = client.post("/predict", files={"file": ("wire.png", contents, "image/png")}, data=processing)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source"] == "upload"
    assert result["filename"] == "wire.png"
    assert result["saved_path"] == result["images"]["1600x1200"]["path"]
    assert result["prediction"] == "ok_wire"
    assert result["confidence"] == 80
    assert_bundle(client, result)
    prepared, _ = module.prepare_image_for_model(module.open_image_from_bytes(contents), module.build_processing_settings(**processing))
    expected = np.asarray(prepared.resize((224, 224)), dtype=np.float32)[None] / 127.5 - 1
    np.testing.assert_array_equal(model.last_input, expected)
    history = client.get("/history").json()["items"]
    assert history[0]["images"] == result["images"]
    assert history[0]["processing"] == result["processing"]
    assert bool(result.get("processed_path")) == bool(processing)
    assert not (module.INSPECTION_DIR / "uploads").exists()
    assert not (module.INSPECTION_DIR / "processed").exists()


@pytest.mark.parametrize("path_kind", ["absolute_legacy", "relative_legacy", "relative_variant", "bare_filename"])
def test_predict_path_backwards_compatibility(api, tmp_path, path_kind):
    module, client, _ = api
    if path_kind == "absolute_legacy":
        path = tmp_path / "old_capture.png"
        value = str(path)
    elif path_kind == "relative_legacy":
        path = module.IMAGE_ROOT / "old_capture.png"
        value = path.name
    else:
        path = module.CAPTURE_DIR / "evidence.png"
        value = f"1600x1200/{path.name}" if path_kind == "relative_variant" else path.name
    path.write_bytes(image_bytes())
    before = path.read_bytes()
    response = client.post("/predict-path", params={"path": value, "brightness": 10})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source"] == "path"
    assert result["path"] == str(path)
    assert_bundle(client, result)
    assert path.read_bytes() == before


class FakeCamera:
    camera_properties = {"Model": "Test camera"}

    def create_still_configuration(self, main):
        assert main["size"] == (1600, 1200)
        return main

    def switch_mode_and_capture_array(self, config):
        return np.zeros((1200, 1600, 3), dtype=np.uint8)

    def capture_array(self):
        return np.zeros((480, 640, 3), dtype=np.uint8)

    def stop(self):
        pass

    def close(self):
        pass


def test_camera_and_hardware_use_same_store(api):
    module, client, _ = api
    module.camera_manager.picam2 = FakeCamera()
    response = client.post("/capture")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source"] == "camera"
    assert result["path"] == result["images"]["1600x1200"]["path"]
    assert_bundle(client, result)
    button = module.hardware_capture_button
    button._capture_lock.acquire()
    button._capture("button-test")
    event = client.get("/hardware-button/status").json()["last_event"]
    assert event["state"] == "complete"
    assert_bundle(client, event["result"])
    assert event["result"]["path"] != result["path"]
    # Live streaming remains in memory; it must not fill the image store.
    before = set(module.IMAGE_ROOT.rglob("*.png"))
    frames = module.mjpeg_frames()
    assert next(frames).startswith(b"--frame\r\nContent-Type: image/jpeg")
    frames.close()
    assert set(module.IMAGE_ROOT.rglob("*.png")) == before
    assert client.post("/camera/stop").json() == {"stopped": True}


def test_wrong_camera_dimensions_are_rejected_without_saving(api):
    module, _, _ = api
    camera = FakeCamera()
    camera.switch_mode_and_capture_array = lambda config: np.zeros((480, 640, 3), dtype=np.uint8)
    module.camera_manager.picam2 = camera
    with pytest.raises(RuntimeError, match="expected 1600x1200"):
        module.capture_and_inspect()
    assert not list(module.IMAGE_ROOT.rglob("*.png"))


def test_stream_http_contract(api, monkeypatch):
    module, client, _ = api
    module.camera_manager.picam2 = FakeCamera()
    frame = next(module.mjpeg_frames())
    monkeypatch.setattr(module, "mjpeg_frames", lambda *args: iter([frame]))
    response = client.get("/camera/stream?brightness=10&wire_overlay=true")
    assert response.status_code == 200
    assert "multipart/x-mixed-replace; boundary=frame" in response.headers["content-type"]
    assert response.content == frame


def test_invalid_requests_do_not_create_images(api):
    module, client, _ = api
    for contents in [b"", b"invalid image"]:
        assert client.post("/predict", files={"file": ("invalid.png", contents)}).status_code == 400
    assert client.post("/predict").status_code == 422
    assert client.post("/predict-path", params={"path": "missing.png"}).status_code == 404
    assert client.post("/predict-path", params={"path": ""}).status_code == 400
    assert client.get("/images/other/file.png").status_code == 404
    assert client.get("/images/224x224/missing.png").status_code == 404
    assert not list(module.IMAGE_ROOT.rglob("*.png"))


def test_status_ui_history_and_routes(api):
    module, client, _ = api
    module.camera_manager.picam2 = FakeCamera()
    status = client.get("/status").json()
    assert status["capture_dir"] == str(module.IMAGE_ROOT / "1600x1200")
    assert set(status["image_directories"]) == {"1600x1200", "640x320", "224x224"}
    assert status["capture_mode"] == "still"
    assert status["hardware_button"]["enabled"] is False
    assert client.get("/").status_code == 200
    ui_response = client.get("/ui/script.js")
    assert ui_response.status_code == 200
    assert ui_response.headers["cache-control"].startswith("no-store")
    assert client.get("/api").status_code == 200
    assert client.get("/camera/status").json()["available"] is True
    module.INSPECTION_DIR.mkdir()
    old = {"id": "old-record", "source": "upload", "source_name": "old.jpg", "confidence": 90}
    module.LOG_FILE.write_text(json.dumps(old) + "\ninvalid line\n")
    assert client.get("/history").json()["items"] == [old]
    assert client.get("/history?limit=0").json()["limit"] == 1
    assert client.get("/history?limit=900").json()["limit"] == 500
    routes = client.get("/openapi.json").json()["paths"]
    assert {"/predict", "/predict-path", "/capture", "/camera/stream", "/camera/stop", "/hardware-button/status", "/history"} <= routes.keys()
