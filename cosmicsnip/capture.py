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
from cosmicsnip.log import get_logger
from cosmicsnip.security import check_no_symlink, validate_path_within, validate_png_magic

from PIL import Image

log = get_logger("capture")


class CaptureError(Exception):
    """Raised when no capture backend succeeds."""


def _validate_image(path: str) -> bool:
    """Check that a captured file is a plausible image within size limits."""
    try:
        with Image.open(path) as img:
            w, h = img.size
            ok = 0 < w <= MAX_IMAGE_WIDTH and 0 < h <= MAX_IMAGE_HEIGHT
            log.debug("Validated image %s: %dx%d  valid=%s", path, w, h, ok)
            return ok
    except Exception as exc:
        log.warning("Image validation failed for %s: %s", path, exc)
        return False


def _capture_cosmic() -> str | None:
    """Use cosmic-screenshot CLI for non-interactive fullscreen capture."""
    save_dir = str(TEMP_DIR)
    cmd = [
        "cosmic-screenshot",
        "--interactive=false",
        f"--save-dir={save_dir}",
        "--notify=false",
    ]
    log.info("Running capture command: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        log.debug("cosmic-screenshot returncode: %d", result.returncode)
        if result.stdout.strip():
            log.debug("cosmic-screenshot stdout: %s", result.stdout.strip())
        if result.stderr.strip():
            log.debug("cosmic-screenshot stderr: %s", result.stderr.strip())

        if result.returncode != 0:
            log.error(
                "cosmic-screenshot exited with code %d. stderr: %s",
                result.returncode,
                result.stderr.strip(),
            )
            return None

        # Find the most recent PNG in our temp dir.
        # cosmic-screenshot saves as Screenshot_YYYY-MM-DD_HH-MM-SS.png
        # cosmic-screenshot saves as: Screenshot_YYYY-MM-DD_HH-MM-SS.png
        # Use the exact format to avoid accidentally picking up user files.
        pattern = os.path.join(save_dir, "Screenshot_????-??-??_??-??-??.png")
        candidates = sorted(
            glob.glob(pattern),
            key=os.path.getmtime,
            reverse=True,
        )
        log.info("Glob pattern: %s  →  %d candidate(s): %s", pattern, len(candidates), candidates)

        for path in candidates:
            try:
                # Security: reject symlinks before chmod (prevents symlink attacks)
                check_no_symlink(path)
                # Security: confirm file is within TEMP_DIR (no traversal)
                validate_path_within(path, TEMP_DIR)
                # Security: check PNG magic bytes before handing to image decoders
                validate_png_magic(path)
            except ValueError as exc:
                log.warning("Security check failed, skipping %s: %s", path, exc)
                continue
            os.chmod(path, TEMP_FILE_MODE)
            if _validate_image(path):
                log.info("Using screenshot file: %s", path)
                return path
            else:
                log.warning("Skipping invalid/oversized file: %s", path)

        log.error("No valid screenshot file found after capture.")
    except FileNotFoundError:
        log.error("cosmic-screenshot not found — is it installed?")
    except subprocess.TimeoutExpired:
        log.error("cosmic-screenshot timed out after 10 seconds.")
    except Exception as exc:
        log.exception("Unexpected error during capture: %s", exc)
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
        "Ensure cosmic-screenshot is installed (ships with Pop!_OS 24.04). "
        f"See log: ~/.local/share/cosmicsnip/cosmicsnip.log"
    )


def cleanup_temp_files(max_age_seconds: int = 3600) -> None:
    """Remove stale temp captures older than max_age_seconds."""
    now = time.time()
    removed = 0
    try:
        for f in list(TEMP_DIR.glob("Screenshot_????-??-??_??-??-??.png")):
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)
                removed += 1
    except Exception as exc:
        log.warning("cleanup_temp_files error: %s", exc)
    if removed:
        log.info("Cleaned up %d stale temp file(s).", removed)
