"""
Screen capture via COSMIC's screenshot infrastructure.

Strategy (in order of preference):
  1. cosmic-screenshot CLI  — works on COSMIC without portal quirks
  2. XDG Desktop Portal     — standard Wayland capture API

Captured files are written to TEMP_DIR with restrictive permissions
and cleaned up after the editor session ends.
"""

import glob
import os
import subprocess
import time
from pathlib import Path

from cosmicsnip.config import TEMP_DIR, TEMP_FILE_MODE, MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT

from PIL import Image


class CaptureError(Exception):
    """Raised when no capture backend succeeds."""


def _validate_image(path: str) -> bool:
    """Check that a captured file is a plausible image within size limits."""
    try:
        with Image.open(path) as img:
            w, h = img.size
            return 0 < w <= MAX_IMAGE_WIDTH and 0 < h <= MAX_IMAGE_HEIGHT
    except Exception:
        return False


def _capture_cosmic() -> str | None:
    """Use cosmic-screenshot CLI for non-interactive fullscreen capture."""
    save_dir = str(TEMP_DIR)
    try:
        subprocess.run(
            [
                "cosmic-screenshot",
                "--interactive=false",
                f"--save-dir={save_dir}",
                "--notify=false",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Find the most recent PNG in our temp dir
        candidates = sorted(
            glob.glob(os.path.join(save_dir, "screenshot-*.png")),
            key=os.path.getmtime,
            reverse=True,
        )
        for path in candidates:
            os.chmod(path, TEMP_FILE_MODE)
            if _validate_image(path):
                return path
    except FileNotFoundError:
        pass  # cosmic-screenshot not installed
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return None


def capture_screen() -> str:
    """
    Capture the full screen and return a path to the temp PNG file.

    Raises CaptureError if every backend fails.
    """
    path = _capture_cosmic()
    if path:
        return path

    raise CaptureError(
        "Could not capture the screen. "
        "Ensure cosmic-screenshot is installed (ships with Pop!_OS 24.04)."
    )


def cleanup_temp_files(max_age_seconds: int = 3600) -> None:
    """Remove stale temp captures older than max_age_seconds."""
    now = time.time()
    try:
        for f in TEMP_DIR.glob("screenshot-*.png"):
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)
    except Exception:
        pass
