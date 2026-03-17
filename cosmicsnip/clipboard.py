"""Desktop notification helper. Clipboard itself uses GTK4 native API (see editor.py)."""

import subprocess

from cosmicsnip.log import get_logger

log = get_logger("clipboard")


def send_notification(title: str, body: str, timeout_ms: int = 2500) -> None:
    """Best-effort notify-send. Fails silently."""
    try:
        subprocess.run(
            ["notify-send", "-i", "edit-copy",
             "-t", str(min(timeout_ms, 30000)),
             title[:200], body[:500]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass
