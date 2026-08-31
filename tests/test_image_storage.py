from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from image_storage import IMAGE_SIZES, ImageStore


def test_dimensions_lossless_model_pixels_and_no_cropping(tmp_path):
    store = ImageStore(tmp_path)
    original = Image.new("RGB", (90, 60), "white")
    processed = Image.new("RGB", (90, 60), "red")
    images = store.save(original, processed)
    for resolution, size in IMAGE_SIZES.items():
        with Image.open(images[resolution]["path"]) as saved:
            assert saved.size == size
            assert saved.mode == "RGB"
    with Image.open(images["224x224"]["path"]) as model_input:
        np.testing.assert_array_equal(model_input, processed.resize((224, 224)))
    with Image.open(images["640x320"]["path"]) as preview:
        assert preview.getpixel((0, 0)) == (0, 0, 0)  # padding, not cropping
        assert preview.getpixel((320, 160)) == (255, 0, 0)
    assert {p.name for p in tmp_path.iterdir()} == set(IMAGE_SIZES)


def test_concurrent_saves_do_not_overwrite(tmp_path):
    store = ImageStore(tmp_path)
    img = Image.new("RGB", (25, 25))
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: store.save(img, img, "../../same"), range(8)))
    assert len({r["224x224"]["path"] for r in results}) == 8
    for resolution in IMAGE_SIZES:
        assert len(list((tmp_path / resolution).iterdir())) == 8


def test_failed_save_cleans_only_its_bundle(tmp_path, monkeypatch):
    store = ImageStore(tmp_path)
    img = Image.new("RGB", (25, 25))
    existing = store.save(img, img)
    save = Image.Image.save

    def fail_on_preview(self, path, **kwargs):
        if Path(path).parent.name == "640x320":
            raise OSError("Disk full")
        return save(self, path, **kwargs)

    monkeypatch.setattr(Image.Image, "save", fail_on_preview)
    with pytest.raises(OSError, match="Disk full"):
        store.save(img, img)
    for resolution in IMAGE_SIZES:
        assert list((tmp_path / resolution).iterdir()) == [Path(existing[resolution]["path"])]


@pytest.mark.parametrize("resolution,filename", [("other", "a.png"), ("224x224", "../secret.png"), ("224x224", "absent.png")])
def test_retrieval_rejects_invalid_paths(tmp_path, resolution, filename):
    with pytest.raises(FileNotFoundError):
        ImageStore(tmp_path).resolve_served_image(resolution, filename)


def test_retrieval_rejects_symlink_escape(tmp_path):
    store = ImageStore(tmp_path / "images")
    secret = tmp_path / "secret.png"
    Image.new("RGB", (10, 10)).save(secret)
    (store.root / "224x224" / "link.png").symlink_to(secret)
    with pytest.raises(FileNotFoundError):
        store.resolve_served_image("224x224", "link.png")
