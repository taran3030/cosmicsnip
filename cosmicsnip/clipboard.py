"""Desktop notification helper. Clipboard itself uses GTK4 native API (see editor.py)."""

import shutil
import subprocess  # nosec B404

from cosmicsnip.log import get_logger

log = get_logger("clipboard")
_NOTIFY_SEND_BIN = shutil.which("notify-send") or "/usr/bin/notify-send"


def send_notification(title: str, body: str, timeout_ms: int = 2500) -> None:
    """Best-effort notify-send. Fails silently."""
    try:
        subprocess.run(
            [_NOTIFY_SEND_BIN, "-i", "edit-copy",
             "-t", str(min(timeout_ms, 30000)),
             title[:200], body[:500]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )  # nosec B603
    except Exception as exc:
        log.debug("notify-send failed: %s", exc)
