"""
Application-wide configuration, constants, and security boundaries.

All magic numbers, paths, and tunable values live here so they're
auditable in one place. File paths are validated before use.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field

# ── Paths ────────────────────────────────────────────────────────────────────

# XDG-compliant directories
_XDG_PICTURES = Path(os.environ.get("XDG_PICTURES_DIR", Path.home() / "Pictures"))
SAVE_DIR: Path = _XDG_PICTURES / "screenshots"
TEMP_DIR: Path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "cosmicsnip"

# ── Security ─────────────────────────────────────────────────────────────────

# Maximum image dimensions we'll process (prevents memory bombs)
MAX_IMAGE_WIDTH: int = 15360   # 16K
MAX_IMAGE_HEIGHT: int = 8640

# Maximum annotation history (prevents unbounded memory growth)
MAX_UNDO_HISTORY: int = 200

# Temp file permissions (owner read/write only)
TEMP_FILE_MODE: int = 0o600

# Allowed MIME types for clipboard
ALLOWED_CLIPBOARD_TYPES: tuple[str, ...] = ("image/png",)

# ── UI Constants ─────────────────────────────────────────────────────────────

# Selection overlay
OVERLAY_DIM_ALPHA: float = 0.45
SELECTION_BORDER_COLOR: tuple[float, ...] = (0.15, 0.56, 1.0, 1.0)
SELECTION_BORDER_WIDTH: float = 2.0
MIN_SELECTION_SIZE: int = 10  # px — ignore micro-drags

# Editor defaults
DEFAULT_PEN_WIDTH: int = 3
DEFAULT_HIGHLIGHT_WIDTH: int = 20
DEFAULT_ARROW_HEAD_ANGLE: float = 0.45  # radians (~26°)
DEFAULT_ARROW_HEAD_RATIO: float = 5.0   # multiplier of pen width

# ── Colors ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolColor:
    """An RGBA color with a human-readable label and icon-safe name."""
    name: str
    label: str
    rgba: tuple[float, float, float, float]

PALETTE: tuple[ToolColor, ...] = (
    ToolColor("red",    "Red",    (0.93, 0.16, 0.16, 1.0)),
    ToolColor("orange", "Orange", (0.96, 0.52, 0.10, 1.0)),
    ToolColor("blue",   "Blue",   (0.15, 0.45, 0.93, 1.0)),
    ToolColor("green",  "Green",  (0.20, 0.72, 0.30, 1.0)),
    ToolColor("black",  "Black",  (0.12, 0.12, 0.12, 1.0)),
    ToolColor("white",  "White",  (1.00, 1.00, 1.00, 1.0)),
)

DEFAULT_COLOR: ToolColor = PALETTE[0]  # Red

# ── Tool Definitions ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolDef:
    """Metadata for a drawing tool."""
    tool_id: str
    label: str
    icon_name: str       # Adwaita symbolic icon
    tooltip: str

TOOLS: tuple[ToolDef, ...] = (
    ToolDef("pen",         "Pen",         "edit-symbolic",              "Freehand pen (P)"),
    ToolDef("highlighter", "Highlighter", "format-text-highlight-symbolic", "Translucent highlighter (H)"),
    ToolDef("arrow",       "Arrow",       "go-next-symbolic",          "Arrow annotation (A)"),
    ToolDef("rectangle",   "Rectangle",   "checkbox-symbolic",         "Rectangle outline (R)"),
)


def ensure_directories() -> None:
    """Create required directories with safe permissions."""
    for d in (SAVE_DIR, TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)
        # Temp dir should be private
        if d == TEMP_DIR:
            os.chmod(d, 0o700)
