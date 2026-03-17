"""Screen capture via cosmic-screenshot CLI.

Takes a full-screen capture (all monitors stitched), validates the PNG,
and returns the path. Temp files are cleaned up between sessions.
"""

import glob
import os
import subprocess
import time
from pathlib import Path

from cosmicsnip.config import TEMP_DIR, TEMP_FILE_MODE, MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT
from cosmicsnip.log import get_logger
from cosmicsnip.security import (
    validate_path_within, open_no_follow, fchmod_safe, validate_png_magic_fd,
)

from PIL import Image

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_WIDTH * MAX_IMAGE_HEIGHT

log = get_logger("capture")


class CaptureError(Exception):
    """Raised when capture fails."""


def _validate_image(path: str) -> bool:
    """Quick sanity check — is it a real image within size limits?"""
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
    """Run cosmic-screenshot in non-interactive mode. Returns path or None."""
    save_dir = str(TEMP_DIR)
    cmd = [
        "cosmic-screenshot",
        "--interactive=false",
        f"--save-dir={save_dir}",
        "--notify=false",
    ]
    log.info("Running capture command: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        log.debug("cosmic-screenshot returncode: %d", result.returncode)
        if result.stdout.strip():
            log.debug("cosmic-screenshot stdout: %s", result.stdout.strip())
        if result.stderr.strip():
            log.debug("cosmic-screenshot stderr: %s", result.stderr.strip())

        if result.returncode != 0:
            log.error("cosmic-screenshot exited %d: %s",
                      result.returncode, result.stderr.strip())
            return None

        # Find the newest screenshot matching cosmic-screenshot's naming
        pattern = os.path.join(save_dir, "Screenshot_????-??-??_??-??-??.png")
        candidates = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        log.info("Glob pattern: %s  →  %d candidate(s)", pattern, len(candidates))
        log.debug("Candidates: %s", candidates)

        for path in candidates:
            fd = None
            try:
                fd = open_no_follow(path)
                validate_path_within(path, TEMP_DIR)
                validate_png_magic_fd(fd, path)
                fchmod_safe(fd, TEMP_FILE_MODE)
            except ValueError as exc:
                log.warning("Security check failed, skipping %s: %s", path, exc)
                continue
            finally:
                if fd is not None:
                    os.close(fd)
            if _validate_image(path):
                log.info("Using screenshot file: %s", path)
                return path
            else:
                log.warning("Skipping invalid/oversized file: %s", path)

        log.error("No valid screenshot found after capture.")
    except FileNotFoundError:
        log.error("cosmic-screenshot not found — is it installed?")
    except subprocess.TimeoutExpired:
        log.error("cosmic-screenshot timed out (10s).")
    except Exception as exc:
        log.exception("Capture error: %s", exc)
    return None


def capture_screen() -> str:
    """Capture full screen, return path. Raises CaptureError on failure."""
    path = _capture_cosmic()
    if path:
        return path
    raise CaptureError(
        "Could not capture the screen. "
        "Ensure cosmic-screenshot is installed (ships with Pop!_OS 24.04). "
        "Check log: ~/.local/share/cosmicsnip/cosmicsnip.log"
    )


def cleanup_temp_files(max_age_seconds: int = 300) -> None:
    """Remove temp captures older than max_age (default 5 min)."""
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


def cleanup_file(path: str) -> None:
    """Remove a specific temp file after it's been consumed."""
    try:
        p = Path(path)
        if p.exists() and str(p).startswith(str(TEMP_DIR)):
            p.unlink(missing_ok=True)
            log.debug("Cleaned up temp file: %s", path)
    except Exception as exc:
        log.warning("cleanup_file error for %s: %s", path, exc)
