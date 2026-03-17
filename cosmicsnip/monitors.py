"""Monitor detection — queries GDK for layout, caches to config file.

GDK on COSMIC reports geometry in logical (compositor) coordinates,
which matches the coordinate space of cosmic-screenshot. No scaling needed.
"""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import gi
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

from cosmicsnip.log import get_logger

log = get_logger("monitors")

_XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_DIR: Path = _XDG_CONFIG / "cosmicsnip"
CONFIG_FILE: Path = CONFIG_DIR / "monitors.json"


@dataclass
class MonitorInfo:
    """One monitor's geometry in the combined screenshot coordinate space."""
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: int = 1
    gdk_index: int = 0


def detect_monitors() -> list[MonitorInfo]:
    """Query GDK for current monitor layout. Sorted left-to-right."""
    display = Gdk.Display.get_default()
    if display is None:
        log.error("No GDK display available.")
        return []

    monitors = display.get_monitors()
    n = monitors.get_n_items()
    log.info("Detected %d monitor(s) via GDK.", n)

    result: list[MonitorInfo] = []
    for i in range(n):
        mon = monitors.get_item(i)
        geom = mon.get_geometry()
        scale = mon.get_scale_factor()
        connector = mon.get_connector() or f"Monitor-{i}"

        # GDK on COSMIC already gives compositor coordinates — don't scale
        info = MonitorInfo(
            name=connector, x=geom.x, y=geom.y,
            width=geom.width, height=geom.height,
            scale=scale, gdk_index=i,
        )
        log.info("  [%d] %s: %dx%d+%d+%d (scale=%d)",
                 i, info.name, info.width, info.height, info.x, info.y, scale)
        result.append(info)

    result.sort(key=lambda m: (m.x, m.y))
    return result


def get_gdk_monitor(gdk_index: int) -> Optional[Gdk.Monitor]:
    """Return the GDK Monitor at the given index, or None."""
    display = Gdk.Display.get_default()
    if display is None:
        return None
    monitors = display.get_monitors()
    if 0 <= gdk_index < monitors.get_n_items():
        return monitors.get_item(gdk_index)
    return None


def save_config(monitors: list[MonitorInfo]) -> None:
    """Atomic write of monitor layout (symlink-safe)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists() and CONFIG_FILE.is_symlink():
        log.warning("Config is a symlink — refusing to write: %s", CONFIG_FILE)
        return

    data = {"version": 1, "monitors": [asdict(m) for m in monitors]}
    tmp = CONFIG_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        tmp.rename(CONFIG_FILE)
        log.info("Monitor config saved: %s", CONFIG_FILE)
    except Exception as exc:
        log.warning("Failed to save monitor config: %s", exc)
        tmp.unlink(missing_ok=True)


def load_config() -> Optional[list[MonitorInfo]]:
    """Load cached monitor layout. Returns None on any problem."""
    if not CONFIG_FILE.is_file() or CONFIG_FILE.is_symlink():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text())
        if not isinstance(data, dict) or data.get("version") != 1:
            return None
        raw = data.get("monitors", [])
        if not isinstance(raw, list) or not raw:
            return None
        result = []
        for m in raw:
            info = MonitorInfo(
                name=str(m["name"]), x=int(m["x"]), y=int(m["y"]),
                width=int(m["width"]), height=int(m["height"]),
                scale=int(m.get("scale", 1)), gdk_index=int(m.get("gdk_index", 0)),
            )
            if info.width <= 0 or info.height <= 0:
                return None
            if info.width > 15360 or info.height > 8640:
                return None
            if not (0 <= info.gdk_index <= 64):
                return None
            if info.x < 0 or info.y < 0:
                return None
            result.append(info)
        log.info("Loaded %d monitor(s) from config.", len(result))
        return result
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        log.warning("Config parse error: %s — regenerating.", exc)
        return None


def get_monitors(force_detect: bool = False) -> list[MonitorInfo]:
    """Get current monitor layout. Detects live, falls back to cache, then 1080p."""
    if not force_detect:
        detected = detect_monitors()
        if detected:
            save_config(detected)
            return detected

    saved = load_config()
    if saved:
        log.info("Using saved monitor config as fallback.")
        return saved

    log.warning("No monitor info — using 1920x1080 default.")
    return [MonitorInfo(name="default", x=0, y=0, width=1920, height=1080)]


def find_monitor_at(monitors: list[MonitorInfo], img_x: int, img_y: int) -> MonitorInfo:
    """Find which monitor contains the given point."""
    for m in monitors:
        if m.x <= img_x < m.x + m.width and m.y <= img_y < m.y + m.height:
            return m
    return monitors[0]
