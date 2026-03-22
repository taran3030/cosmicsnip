"""Config — paths, constants, tool/color definitions. Single source of truth."""

import os
import sys
from pathlib import Path
from dataclasses import dataclass

from cosmicsnip.log import get_logger
from cosmicsnip.security import verify_dir_ownership

log = get_logger("config")

# ── Paths ────────────────────────────────────────────────────────────────────


def _xdg_path(env_var: str, default: Path) -> Path:
    """Resolve an XDG path, reject values outside home/run/tmp."""
    raw = os.environ.get(env_var)
    if raw is None:
        return default
    resolved = Path(raw).resolve()
    home = str(Path.home().resolve())
    if not any(str(resolved).startswith(r) for r in (home, "/run", "/tmp")):
        return default
    return resolved


_XDG_PICTURES = _xdg_path("XDG_PICTURES_DIR", Path.home() / "Pictures")
SAVE_DIR: Path = _XDG_PICTURES / "screenshots"

_XDG_RUNTIME = _xdg_path("XDG_RUNTIME_DIR", Path("/tmp"))
TEMP_DIR: Path = _XDG_RUNTIME / "cosmicsnip"

# ── Limits ───────────────────────────────────────────────────────────────────

MAX_IMAGE_WIDTH: int = 15360
MAX_IMAGE_HEIGHT: int = 8640
MAX_UNDO_HISTORY: int = 200
MAX_STROKE_POINTS: int = 10000
TEMP_FILE_MODE: int = 0o600
ALLOWED_CLIPBOARD_TYPES: tuple[str, ...] = ("image/png",)

# ── Overlay ──────────────────────────────────────────────────────────────────

OVERLAY_DIM_ALPHA: float = 0.45
SELECTION_BORDER_COLOR: tuple[float, ...] = (0.15, 0.56, 1.0, 1.0)
SELECTION_BORDER_WIDTH: float = 2.0
MIN_SELECTION_SIZE: int = 10

# ── Editor defaults ──────────────────────────────────────────────────────────

DEFAULT_PEN_WIDTH: int = 3
DEFAULT_HIGHLIGHT_WIDTH: int = 20
DEFAULT_ARROW_HEAD_ANGLE: float = 0.45   # radians (~26 deg)
DEFAULT_ARROW_HEAD_RATIO: float = 5.0    # arrowhead = width * ratio

# ── Colors ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolColor:
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

DEFAULT_COLOR: ToolColor = PALETTE[0]

# ── Tools ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolDef:
    tool_id: str
    label: str
    icon_name: str
    tooltip: str


TOOLS: tuple[ToolDef, ...] = (
    ToolDef("pen",         "Pen",         "edit-symbolic",                    "Freehand pen (P)"),
    ToolDef("highlighter", "Highlighter", "format-text-highlight-symbolic",   "Highlighter (H)"),
    ToolDef("arrow",       "Arrow",       "go-next-symbolic",                 "Arrow (A)"),
    ToolDef("rect",        "Rectangle",   "checkbox-symbolic",                "Rectangle (R)"),
)

# ── Directory setup ──────────────────────────────────────────────────────────


def ensure_directories() -> None:
    """Create SAVE_DIR and TEMP_DIR with safe permissions."""
    for d in (SAVE_DIR, TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)
        if d == TEMP_DIR:
            os.chmod(d, 0o700)
            try:
                verify_dir_ownership(d)
            except ValueError as exc:
                log.critical("TEMP_DIR check failed: %s", exc)
                log.critical("Delete '%s' and re-run, or check for tampering.", d)
                sys.exit(1)
