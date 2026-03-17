"""Logging — stderr + rotating file at ~/.local/share/cosmicsnip/cosmicsnip.log."""

import logging
import logging.handlers
import os
from pathlib import Path

LOG_DIR = Path.home() / ".local" / "share" / "cosmicsnip"
LOG_FILE = LOG_DIR / "cosmicsnip.log"

_fmt = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup_logging(debug: bool = False) -> None:
    """Call once at startup. All later get_logger() calls inherit this config."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger("cosmicsnip")
    root.setLevel(level)

    if not LOG_FILE.exists():
        LOG_FILE.touch(mode=0o600)
    else:
        os.chmod(LOG_FILE, 0o600)

    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(_fmt)
    fh.setLevel(level)
    root.addHandler(fh)

    for backup in LOG_DIR.glob("cosmicsnip.log.*"):
        try:
            os.chmod(backup, 0o600)
        except OSError:
            pass

    sh = logging.StreamHandler()
    sh.setFormatter(_fmt)
    sh.setLevel(level)
    root.addHandler(sh)

    root.info("=== CosmicSnip starting ===")
    root.info("Log file: %s", LOG_FILE)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger: cosmicsnip.<name>."""
    return logging.getLogger(f"cosmicsnip.{name}")
