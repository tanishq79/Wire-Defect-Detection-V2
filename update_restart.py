"""Apply a local SurfaceAI update after the active server has stopped.

This helper is deliberately detached from the FastAPI process.  It allows the
API to return a confirmation to the dashboard, then terminates the server,
updates Git and runtime dependencies, and launches the updated application.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time


def run_logged(log_file: Path, command: list[str], project_dir: Path) -> bool:
    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"$ {' '.join(command)}\n")
        result = subprocess.run(command, cwd=project_dir, stdout=log, stderr=subprocess.STDOUT, check=False)
        log.write(f"exit={result.returncode}\n")
    return result.returncode == 0


def stop_server(server_pid: int) -> None:
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/PID", str(server_pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.kill(server_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def start_updated_app(project_dir: Path, python: str, port: int, launcher: str, log_file: Path) -> None:
    if launcher == "pi":
        command = ["/usr/bin/bash", str(project_dir / "start_surfaceai_desktop.sh")]
    else:
        command = [python, str(project_dir / "run_desktop.py"), "--port", str(port)]

    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"Starting updated application: {' '.join(command)}\n")
        options = {"cwd": project_dir, "stdout": log, "stderr": subprocess.STDOUT, "close_fds": True}
        if platform.system() == "Windows":
            options["creationflags"] = 0x00000008 | 0x00000200
        else:
            options["start_new_session"] = True
        subprocess.Popen(command, **options)


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled SurfaceAI update and restart helper")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--server-pid", required=True, type=int)
    parser.add_argument("--python", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--launcher", choices=("desktop", "pi"), required=True)
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    log_file = project_dir / "inspection_data" / "software_update.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"\nControlled update started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Keep the API alive long enough to return the scheduled-update response.
    time.sleep(1.5)
    stop_server(args.server_pid)
    time.sleep(1.0)

    git = "git.exe" if platform.system() == "Windows" else "git"
    updated = run_logged(log_file, [git, "fetch", "origin", "main"], project_dir)
    if updated:
        updated = run_logged(log_file, [git, "pull", "--ff-only", "origin", "main"], project_dir)
    if updated:
        run_logged(log_file, [args.python, "-m", "pip", "install", "-r", "requirements.txt"], project_dir)

    # Even if Git or dependency installation failed, restart the last intact
    # installation so a worker is not left with a permanently stopped station.
    start_updated_app(project_dir, args.python, args.port, args.launcher, log_file)


if __name__ == "__main__":
    main()
