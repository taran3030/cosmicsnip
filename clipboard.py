"""
Clipboard operations for Wayland via wl-copy.

Security notes:
  - We only write image/png MIME type (no arbitrary data).
  - File contents are read in binary mode and piped via stdin
    to avoid shell injection through filenames.
  - Subprocess runs without shell=True.
"""

import subprocess
from pathlib import Path

from cosmicsnip.config import ALLOWED_CLIPBOARD_TYPES


class ClipboardError(Exception):
    """Raised when clipboard operations fail."""


def copy_image_to_clipboard(image_path: str | Path) -> None:
    """
    Copy a PNG image file to the Wayland clipboard.

    Args:
        image_path: Path to a PNG file.

    Raises:
        ClipboardError: If wl-copy is not found or the operation fails.
        FileNotFoundError: If the image file doesn't exist.
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    mime_type = ALLOWED_CLIPBOARD_TYPES[0]  # "image/png"

    try:
        image_data = image_path.read_bytes()
    except PermissionError as exc:
        raise ClipboardError(f"Cannot read image file: {exc}") from exc

    try:
        proc = subprocess.run(
            ["wl-copy", "--type", mime_type],
            input=image_data,
            capture_output=True,
            timeout=5,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace").strip()
            raise ClipboardError(f"wl-copy failed: {stderr}")
    except FileNotFoundError:
        raise ClipboardError(
            "wl-copy not found. Install it with: sudo apt install wl-clipboard"
        )
    except subprocess.TimeoutExpired:
        raise ClipboardError("Clipboard operation timed out.")


def send_notification(title: str, body: str, timeout_ms: int = 2500) -> None:
    """Best-effort desktop notification. Fails silently."""
    try:
        subprocess.Popen(
            [
                "notify-send",
                "-i", "edit-copy",
                "-t", str(timeout_ms),
                title,
                body,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
