"""Validate prerequisites without exposing credentials or modifying source."""

import importlib.util
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failures = []
for binary in ["ffmpeg", "ffprobe"]:
    present = bool(shutil.which(binary))
    print(f"{'OK' if present else 'MISSING'} {binary}")
    if not present:
        failures.append(binary)
if shutil.which("ffmpeg"):
    encoders = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True
    ).stdout
    filters = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    ).stdout
    for name, present in [
        ("libx264", "libx264" in encoders),
        ("libass subtitles", " ass " in filters),
    ]:
        print(f"{'OK' if present else 'MISSING'} {name}")
        if not present:
            failures.append(name)
for module in ["fastapi", "uvicorn", "httpx"]:
    present = importlib.util.find_spec(module) is not None
    print(f"{'OK' if present else 'MISSING'} {module}")
    if not present:
        failures.append(module)
if not (ROOT / "apps/web/dist/index.html").is_file():
    failures.append("frontend build")
try:
    with socket.socket() as port:
        port.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port.bind(("127.0.0.1", 8000))
except OSError:
    failures.append("port 8000 is already occupied")
print(f"Platform: {platform.system()} {platform.machine()}")
print(
    "ASR: "
    + (
        "Apple Silicon supported"
        if platform.system() == "Darwin" and platform.machine() == "arm64"
        else "SRT import available; MLX requires Apple Silicon"
    )
)
if failures:
    print("Cannot start: " + ", ".join(failures), file=sys.stderr)
    sys.exit(1)
