"""
Fullscreen selection overlay.

Displays the captured screenshot under a semi-transparent dim layer.
The user drags to select a rectangular region, which is highlighted
in real time. Releasing the mouse finalises the selection and hands
the crop coordinates back to the caller via a callback.

Multi-monitor: cosmic-screenshot captures all monitors into one combined
image. This overlay detects which monitor it is on, crops to that monitor's
region, and pre-scales it once for fast rendering.

Keyboard:
  Escape — cancel and close.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_foreign("cairo")  # bridge pycairo ↔ PyGObject cairo types

from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
from typing import Callable

from cosmicsnip.log import get_logger
from cosmicsnip.config import (
    OVERLAY_DIM_ALPHA,
    SELECTION_BORDER_COLOR,
    SELECTION_BORDER_WIDTH,
    MIN_SELECTION_SIZE,
)

log = get_logger("overlay")


class SelectionOverlay(Gtk.Window):
    """
    A frameless fullscreen window for region selection.

    Args:
        app: The parent Gtk.Application.
        image_path: Filesystem path to the fullscreen capture (may span all monitors).
        on_selected: Callback receiving (image_path, x1, y1, x2, y2) in image coords.
        on_cancelled: Callback with no args when user presses Escape.
    """

    def __init__(
        self,
        app: Gtk.Application,
        image_path: str,
        on_selected: Callable[[str, int, int, int, int], None],
        on_cancelled: Callable[[], None],
    ):
        super().__init__(application=app)
        self._image_path = image_path
        self._on_selected = on_selected
        self._on_cancelled = on_cancelled

        # Load full combined screenshot (may span multiple monitors)
        log.info("Loading screenshot into overlay: %s", image_path)
        self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        self._img_w = self._pixbuf.get_width()
        self._img_h = self._pixbuf.get_height()
        log.info("Pixbuf loaded: %dx%d px", self._img_w, self._img_h)

        # Display cache — set once the window is mapped and we know which monitor we're on
        self._display_pixbuf: GdkPixbuf.Pixbuf | None = None
        # Portion of the full image that corresponds to THIS monitor (image pixels)
        self._img_offset_x: int = 0
        self._img_offset_y: int = 0
        self._img_mon_w: int = self._img_w
        self._img_mon_h: int = self._img_h

        # Drag state
        self._dragging = False
        self._sx = self._sy = 0.0
        self._ex = self._ey = 0.0
        self._has_selection = False

        # Window chrome
        self.set_decorated(False)
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))

        # Root overlay
        root = Gtk.Overlay()

        # Canvas
        self._canvas = Gtk.DrawingArea()
        self._canvas.set_hexpand(True)
        self._canvas.set_vexpand(True)
        self._canvas.set_draw_func(self._draw)
        root.set_child(self._canvas)

        # Instruction pill
        pill = Gtk.Label(label="  Drag to select  ·  Esc to cancel  ")
        pill.set_halign(Gtk.Align.CENTER)
        pill.set_valign(Gtk.Align.START)
        pill.set_margin_top(24)
        pill.add_css_class("snip-pill")
        root.add_overlay(pill)

        self.set_child(root)
        self.fullscreen()

        # Build the display cache after the window is mapped (allocation is final)
        self.connect("map", self._on_mapped)

        # ── Input controllers ────────────────────────────────────────────
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._on_press)
        click.connect("released", self._on_release)
        self._canvas.add_controller(click)

        drag = Gtk.GestureDrag()
        drag.connect("drag-update", self._on_drag_update)
        self._canvas.add_controller(drag)

        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

    # ── Display cache ────────────────────────────────────────────────────

    def _on_mapped(self, _window):
        """Window is now visible and has a real allocation — build the display cache."""
        GLib.idle_add(self._build_display_cache)

    def _build_display_cache(self):
        """
        Determine which monitor this overlay is on, crop the combined screenshot
        to just that monitor's region, then pre-scale to canvas size.
        This runs once; all subsequent draws just blit the cached pixbuf.
        """
        alloc = self._canvas.get_allocation()
        canvas_w, canvas_h = alloc.width, alloc.height
        log.info("Building display cache: canvas=%dx%d", canvas_w, canvas_h)

        if canvas_w <= 0 or canvas_h <= 0:
            log.warning("Canvas has no allocation yet — retrying in 50 ms.")
            GLib.timeout_add(50, self._build_display_cache)
            return GLib.SOURCE_REMOVE

        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        n = monitors.get_n_items()

        # Find the bounding box of all monitors in logical coords
        max_x = max_y = 0
        for i in range(n):
            g = monitors.get_item(i).get_geometry()
            max_x = max(max_x, g.x + g.width)
            max_y = max(max_y, g.y + g.height)
        log.info("Total logical desktop: %dx%d  (image: %dx%d  monitors: %d)",
                 max_x, max_y, self._img_w, self._img_h, n)

        # Scale factor: logical coords → image pixels
        sx = self._img_w / max_x if max_x > 0 else 1.0
        sy = self._img_h / max_y if max_y > 0 else 1.0
        log.info("Logical→image scale: sx=%.3f  sy=%.3f", sx, sy)

        # Find which monitor this window is on
        surface = self.get_surface()
        if surface and n > 0:
            mon = display.get_monitor_at_surface(surface)
        else:
            mon = monitors.get_item(0)

        g = mon.get_geometry()
        log.info("This monitor: logical (%d,%d) %dx%d", g.x, g.y, g.width, g.height)

        self._img_offset_x = int(g.x * sx)
        self._img_offset_y = int(g.y * sy)
        self._img_mon_w = int(g.width * sx)
        self._img_mon_h = int(g.height * sy)

        # Clamp to image bounds
        self._img_offset_x = min(self._img_offset_x, self._img_w)
        self._img_offset_y = min(self._img_offset_y, self._img_h)
        self._img_mon_w = min(self._img_mon_w, self._img_w - self._img_offset_x)
        self._img_mon_h = min(self._img_mon_h, self._img_h - self._img_offset_y)

        log.info("Monitor region in image: offset=(%d,%d) size=%dx%d",
                 self._img_offset_x, self._img_offset_y,
                 self._img_mon_w, self._img_mon_h)

        try:
            # Crop to this monitor's region, then scale to canvas size in one step
            sub = self._pixbuf.new_subpixbuf(
                self._img_offset_x, self._img_offset_y,
                self._img_mon_w, self._img_mon_h,
            )
            self._display_pixbuf = sub.scale_simple(
                canvas_w, canvas_h, GdkPixbuf.InterpType.BILINEAR
            )
            log.info("Display cache ready: %dx%d", canvas_w, canvas_h)
        except Exception as exc:
            log.error("Failed to build display cache: %s — falling back to full image", exc)
            self._display_pixbuf = self._pixbuf

        self._canvas.queue_draw()
        return GLib.SOURCE_REMOVE

    # ── Drawing ──────────────────────────────────────────────────────────

    def _draw(self, _area, cr, w: int, h: int):
        if w == 0 or h == 0:
            return

        if self._display_pixbuf is None:
            # Cache not ready yet — draw a plain dark background
            cr.set_source_rgb(0.08, 0.08, 0.08)
            cr.paint()
            return

        # Background: pre-scaled screenshot — 1:1 blit, no per-frame scaling
        Gdk.cairo_set_source_pixbuf(cr, self._display_pixbuf, 0, 0)
        cr.paint()

        # Dim layer
        cr.set_source_rgba(0, 0, 0, OVERLAY_DIM_ALPHA)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        if not self._has_selection:
            return

        x1, y1 = min(self._sx, self._ex), min(self._sy, self._ey)
        x2, y2 = max(self._sx, self._ex), max(self._sy, self._ey)
        sw, sh = x2 - x1, y2 - y1

        if sw < 2 or sh < 2:
            return

        # Bright cutout: clip to selection rect and repaint the cached pixbuf
        cr.save()
        cr.rectangle(x1, y1, sw, sh)
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, self._display_pixbuf, 0, 0)
        cr.paint()
        cr.restore()

        # Selection border
        r, g, b, a = SELECTION_BORDER_COLOR
        cr.set_source_rgba(r, g, b, a)
        cr.set_line_width(SELECTION_BORDER_WIDTH)
        cr.rectangle(x1, y1, sw, sh)
        cr.stroke()

        # Dimension badge (in image pixels)
        kx = self._img_mon_w / w if w else 1.0
        ky = self._img_mon_h / h if h else 1.0
        iw, ih = int(sw * kx), int(sh * ky)
        dim = f"{iw} × {ih}"
        cr.set_font_size(12)
        ext = cr.text_extents(dim)
        bx = x1
        by = min(y2 + 8, h - 28)  # keep badge on screen
        cr.set_source_rgba(0, 0, 0, 0.8)
        cr.rectangle(bx, by, ext.width + 16, 24)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(bx + 8, by + 17)
        cr.show_text(dim)

    # ── Input handlers ───────────────────────────────────────────────────

    def _on_press(self, _gesture, _n, x, y):
        self._dragging = True
        self._sx = self._ex = x
        self._sy = self._ey = y
        self._has_selection = True

    def _on_drag_update(self, gesture, dx, dy):
        if not self._dragging:
            return
        ok, ox, oy = gesture.get_start_point()
        if ok:
            self._ex = ox + dx
            self._ey = oy + dy
            self._canvas.queue_draw()

    def _on_release(self, _gesture, _n, x, y):
        self._dragging = False
        self._ex, self._ey = x, y
        self._canvas.queue_draw()

        sw = abs(self._ex - self._sx)
        sh = abs(self._ey - self._sy)

        if sw >= MIN_SELECTION_SIZE and sh >= MIN_SELECTION_SIZE:
            self._finalise()

    def _on_key(self, _ctl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self._on_cancelled()
            self.close()
            return True
        return False

    # ── Finalise ─────────────────────────────────────────────────────────

    def _finalise(self):
        """Convert canvas coords → image coords and invoke callback."""
        alloc = self._canvas.get_allocation()
        log.info("Finalising selection: canvas alloc=%dx%d", alloc.width, alloc.height)
        if alloc.width == 0 or alloc.height == 0:
            log.error("Canvas has zero allocation — cannot finalise.")
            return

        # Scale from canvas coords to monitor-region image coords
        kx = self._img_mon_w / alloc.width
        ky = self._img_mon_h / alloc.height

        x1 = self._img_offset_x + max(0, int(min(self._sx, self._ex) * kx))
        y1 = self._img_offset_y + max(0, int(min(self._sy, self._ey) * ky))
        x2 = self._img_offset_x + min(self._img_mon_w, int(max(self._sx, self._ex) * kx))
        y2 = self._img_offset_y + min(self._img_mon_h, int(max(self._sy, self._ey) * ky))

        # Clamp to full image bounds
        x1 = max(0, min(x1, self._img_w))
        y1 = max(0, min(y1, self._img_h))
        x2 = max(0, min(x2, self._img_w))
        y2 = max(0, min(y2, self._img_h))

        log.info(
            "Selection: screen=(%.1f,%.1f)→(%.1f,%.1f)  image=(%d,%d)→(%d,%d)  size=%dx%d",
            self._sx, self._sy, self._ex, self._ey,
            x1, y1, x2, y2, x2 - x1, y2 - y1,
        )
        self.close()
        self._on_selected(self._image_path, x1, y1, x2, y2)
