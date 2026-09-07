"""The single store for runtime inspection images (independent of TensorFlow)."""
from datetime import datetime, timezone
from pathlib import Path
import os

from PIL import Image, ImageOps


APP_DIR = Path(__file__).resolve().parent
IMAGE_SIZES = {"1600x1200": (1600, 1200), "640x320": (640, 320), "224x224": (224, 224)}


def configured_path(variable: str, default: str) -> Path:
    path = Path(os.getenv(variable, default)).expanduser()
    return (path if path.is_absolute() else APP_DIR / path).resolve()


class ImageStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        for resolution in IMAGE_SIZES:
            (self.root / resolution).mkdir(parents=True, exist_ok=True)

    def save(
        self,
        original: Image.Image,
        processed: Image.Image,
        stem: str = "inspection",
        machine_number: int | None = None,
    ) -> dict:
        """Save a unique lossless bundle; model pixels match the previous resize."""
        now = datetime.now().astimezone()
        machine_part = f"machine-{int(machine_number)}" if machine_number is not None else "machine-unknown"
        # Microseconds keep names unique while leaving the requested fields easy to read.
        filename = f"{now:%Y-%m-%d_%H-%M-%S-%f}_{machine_part}.png"
        variants = {
            "1600x1200": ImageOps.pad(original.convert("RGB"), (1600, 1200), method=Image.Resampling.LANCZOS),
            "640x320": ImageOps.pad(processed.convert("RGB"), (640, 320), method=Image.Resampling.LANCZOS),
            # PIL's previous RGB resize default was BICUBIC. Do not pad the ML input.
            "224x224": processed.convert("RGB").resize((224, 224), Image.Resampling.BICUBIC),
        }
        images = {}
        written = []
        temporary = []
        try:
            for resolution, img in variants.items():
                path = self.root / resolution / filename
                temp = path.with_suffix(".tmp")
                temporary.append(temp)
                img.save(temp, format="PNG")
                temp.replace(path)
                written.append(path)
                images[resolution] = {
                    "path": str(path), "url": f"/images/{resolution}/{filename}",
                    "width": img.width, "height": img.height,
                }
        except Exception:
            # Only remove files created by this failed, uniquely named bundle.
            for path in temporary + written:
                path.unlink(missing_ok=True)
            raise
        return images

    def resolve_served_image(self, resolution: str, filename: str) -> Path:
        if resolution not in IMAGE_SIZES or Path(filename).name != filename:
            raise FileNotFoundError("Unknown image")
        directory = (self.root / resolution).resolve()
        path = (directory / filename).resolve()
        if directory.parent != self.root or path.parent != directory or not path.is_file():
            raise FileNotFoundError("Unknown image")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            raise FileNotFoundError("Unknown image")
        return path
