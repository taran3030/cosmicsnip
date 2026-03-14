"""
Logging setup for CosmicSnip.

Writes to both stderr (visible in terminal) and a rotating log file at
~/.local/share/cosmicsnip/cosmicsnip.log so errors are always capturable.
"""

import logging
import logging.handlers
from pathlib import Path


LOG_DIR = Path.home() / ".local" / "share" / "cosmicsnip"
LOG_FILE = LOG_DIR / "cosmicsnip.log"

# Module-level logger — each module does: from cosmicsnip.log import get_logger
_fmt = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup_logging(debug: bool = False) -> None:
    """
    Call once at startup (in main()). Subsequent get_logger() calls
    automatically use the configured root logger.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger("cosmicsnip")
    root.setLevel(level)

    # Rotating file handler — keeps last 3 runs, 512 KB each
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(_fmt)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # Stderr handler — visible when running from terminal
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(_fmt)
    stderr_handler.setLevel(level)
    root.addHandler(stderr_handler)

    root.info("=== CosmicSnip starting ===")
    root.info("Log file: %s", LOG_FILE)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the cosmicsnip namespace."""
    return logging.getLogger(f"cosmicsnip.{name}")
