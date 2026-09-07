"""Cross-platform launcher for SurfaceAI manual inspection mode.

This launcher intentionally does not require Raspberry Pi hardware. On Windows,
macOS, and standard Linux computers the dashboard supports upload, stored-image
inspection, reports, and TensorFlow inference. Camera, GPIO buttons, and motor
controls are automatically unavailable outside Raspberry Pi Linux.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import threading
import time
import webbrowser


def require_module(module: str, package: str) -> None:
    if importlib.util.find_spec(module) is None:
        raise SystemExit(
            f"Missing dependency: {package}.\n"
            "Create a virtual environment and run: python -m pip install -r requirements.txt"
        )


def open_browser(url: str) -> None:
    time.sleep(1.5)
    webbrowser.open(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start SurfaceAI on any supported desktop OS.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: localhost only).")
    parser.add_argument("--port", type=int, default=8000, help="Port number (default: 8000).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the default browser.")
    args = parser.parse_args()

    require_module("uvicorn", "uvicorn")
    require_module("tensorflow", "tensorflow")
    require_module("PIL", "pillow")

    url = f"http://{args.host}:{args.port}/ui/"
    if not args.no_browser:
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    import uvicorn

    print(f"SurfaceAI desktop mode: {url}")
    print("Hardware camera, GPIO, and motor controls are optional and unavailable on non-Pi systems.")
    uvicorn.run("app:app", host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
