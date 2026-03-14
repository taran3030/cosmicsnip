"""
overlay.py — Fullscreen region-selection overlay.

Displays the captured screenshot (which may span multiple monitors as one
combined image) scaled to fit the overlay window. The user drags to select
a rectangular region; releasing the mouse finalises the selection and fires
the on_selected callback with image-space coordinates.

Multi-monitor strategy:
    cosmic-screenshot captures all monitors into a single combined image.
    Rather than trying to place separate overlay windows on each monitor
    (which COSMIC's Wayland compositor does not honour), this module scales
    the entire combined image to fit one fullscreen window. The user can
    select content from any monitor in a single interaction.

Keyboard:
    Escape — cancel and close.

Changes:
    - Replaced per-monitor cropping with fit-to-canvas scaling so both
      monitors are visible and selectable in a single overlay window.
    - Added retry loop when canvas allocation is 0×0 at map time.
    - Fixed Escape key to close before firing the cancel callback.
    - Added return GLib.SOURCE_REMOVE from cache builder for timeout safety.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_foreign("cairo")

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
    Frameless fullscreen window for region selection.

    Scales the full combined screenshot to fit the window, preserving aspect
    ratio (letterbox/pillarbox). The user drags a rectangle; on release the
    canvas coordinates are mapped back to full image coordinates and passed
    to the on_selected callback.

    Args:
        app:         The parent Gtk.Application.
        image_path:  Path to the fullscreen capture (may span all monitors).
        on_selected: Callback — (image_path, x1, y1, x2, y2) in image pixels.
        on_cancelled: Callback — no args, called on Escape.
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

        # ── Load screenshot ───────────────────────────────────────────────
        log.info("Loading screenshot into overlay: %s", image_path)
        self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        self._img_w = self._pixbuf.get_width()
        self._img_h = self._pixbuf.get_height()
        log.info("Pixbuf loaded: %dx%d px", self._img_w, self._img_h)

        # ── Display cache ─────────────────────────────────────────────────
        # Set once the window is mapped and we know the canvas size.
        # _disp_x/y: top-left corner of the scaled image within the canvas.
        # _disp_w/h: pixel size of the scaled image on-canvas.
        # _disp_scale: factor applied to go from image pixels → canvas pixels.
        self._display_pixbuf: GdkPixbuf.Pixbuf | None = None
        self._disp_x: int = 0
        self._disp_y: int = 0
        self._disp_w: int = self._img_w
        self._disp_h: int = self._img_h
        self._disp_scale: float = 1.0

        # ── Drag state ────────────────────────────────────────────────────
        self._dragging = False
        self._sx = self._sy = 0.0
        self._ex = self._ey = 0.0
        self._has_selection = False

        # ── Window setup ──────────────────────────────────────────────────
        self.set_decorated(False)
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))
        self.fullscreen()

        # ── Widget tree ───────────────────────────────────────────────────
        root = Gtk.Overlay()

        self._canvas = Gtk.DrawingArea()
        self._canvas.set_hexpand(True)
        self._canvas.set_vexpand(True)
        self._canvas.set_draw_func(self._draw)
        root.set_child(self._canvas)

        pill = Gtk.Label(label="  Drag to select  ·  Esc to cancel  ")
        pill.set_halign(Gtk.Align.CENTER)
        pill.set_valign(Gtk.Align.START)
        pill.set_margin_top(24)
        pill.add_css_class("snip-pill")
        root.add_overlay(pill)

        self.set_child(root)

        # ── Input controllers ─────────────────────────────────────────────
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

        self.connect("map", self._on_mapped)

    # ── Display cache ─────────────────────────────────────────────────────

    def _on_mapped(self, _window):
        """Kick off cache build once the window has a real allocation."""
        GLib.idle_add(self._build_display_cache)

    def _build_display_cache(self):
        """
        Scale the full combined screenshot to fit the canvas (aspect-ratio
        preserved). Stores the scaled pixbuf and the offset/scale values
        used by _draw and _finalise. Retries every 50 ms if the canvas has
        not received its allocation yet.
        """
        alloc = self._canvas.get_allocation()
        canvas_w, canvas_h = alloc.width, alloc.height

        if canvas_w <= 0 or canvas_h <= 0:
            log.warning("Canvas has no allocation yet — retrying in 50 ms.")
            GLib.timeout_add(50, self._build_display_cache)
            return GLib.SOURCE_REMOVE

        scale = min(canvas_w / self._img_w, canvas_h / self._img_h)
        disp_w = int(self._img_w * scale)
        disp_h = int(self._img_h * scale)

        self._disp_x = (canvas_w - disp_w) // 2
        self._disp_y = (canvas_h - disp_h) // 2
        self._disp_w = disp_w
        self._disp_h = disp_h
        self._disp_scale = scale

        log.info(
            "Display cache: canvas=%dx%d  image=%dx%d  scale=%.3f  offset=(%d,%d)",
            canvas_w, canvas_h, disp_w, disp_h, scale, self._disp_x, self._disp_y,
        )

        try:
            self._display_pixbuf = self._pixbuf.scale_simple(
                disp_w, disp_h, GdkPixbuf.InterpType.BILINEAR
            )
        except Exception as exc:
            log.error("scale_simple failed: %s — using unscaled pixbuf", exc)
            self._display_pixbuf = self._pixbuf

        self._canvas.queue_draw()
        return GLib.SOURCE_REMOVE

    # ── Drawing ───────────────────────────────────────────────────────────

    def _draw(self, _area, cr, w: int, h: int):
        """
        Render: black fill → scaled screenshot → dim layer → selection rect.
        The screenshot is painted at (_disp_x, _disp_y) so black bars appear
        for any space not covered by the image (letterbox / pillarbox).
        """
        cr.set_source_rgb(0, 0, 0)
        cr.paint()

        if self._display_pixbuf is None:
            return

        Gdk.cairo_set_source_pixbuf(cr, self._display_pixbuf, self._disp_x, self._disp_y)
        cr.paint()

        cr.set_source_rgba(0, 0, 0, OVERLAY_DIM_ALPHA)
        cr.rectangle(self._disp_x, self._disp_y, self._disp_w, self._disp_h)
        cr.fill()

        if not self._has_selection:
            return

        x1, y1, x2, y2 = self._clamped_selection()
        sw, sh = x2 - x1, y2 - y1

        if sw < 2 or sh < 2:
            return

        cr.save()
        cr.rectangle(x1, y1, sw, sh)
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, self._display_pixbuf, self._disp_x, self._disp_y)
        cr.paint()
        cr.restore()

        r, g, b, a = SELECTION_BORDER_COLOR
        cr.set_source_rgba(r, g, b, a)
        cr.set_line_width(SELECTION_BORDER_WIDTH)
        cr.rectangle(x1, y1, sw, sh)
        cr.stroke()

        iw = int(sw / self._disp_scale)
        ih = int(sh / self._disp_scale)
        dim = f"{iw} × {ih}"
        cr.set_font_size(12)
        ext = cr.text_extents(dim)
        bx = x1
        by = min(y2 + 8, h - 28)
        cr.set_source_rgba(0, 0, 0, 0.8)
        cr.rectangle(bx, by, ext.width + 16, 24)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(bx + 8, by + 17)
        cr.show_text(dim)

    # ── Input handlers ────────────────────────────────────────────────────

    def _on_press(self, _gesture, _n, x, y):
        """Begin drag; clamp start point to the image area."""
        x = max(self._disp_x, min(x, self._disp_x + self._disp_w))
        y = max(self._disp_y, min(y, self._disp_y + self._disp_h))
        self._dragging = True
        self._sx = self._ex = x
        self._sy = self._ey = y
        self._has_selection = True

    def _on_drag_update(self, gesture, dx, dy):
        """Update drag end-point; clamp to image area."""
        if not self._dragging:
            return
        ok, ox, oy = gesture.get_start_point()
        if ok:
            self._ex = max(self._disp_x, min(ox + dx, self._disp_x + self._disp_w))
            self._ey = max(self._disp_y, min(oy + dy, self._disp_y + self._disp_h))
            self._canvas.queue_draw()

    def _on_release(self, _gesture, _n, x, y):
        """End drag; finalise if the selection meets the minimum size."""
        self._dragging = False
        self._ex = max(self._disp_x, min(x, self._disp_x + self._disp_w))
        self._ey = max(self._disp_y, min(y, self._disp_y + self._disp_h))
        self._canvas.queue_draw()

        x1, y1, x2, y2 = self._clamped_selection()
        if (x2 - x1) >= MIN_SELECTION_SIZE and (y2 - y1) >= MIN_SELECTION_SIZE:
            self._finalise()

    def _on_key(self, _ctl, keyval, _keycode, _state):
        """Close first, then fire callback — matches the _finalise pattern."""
        if keyval == Gdk.KEY_Escape:
            self.close()
            self._on_cancelled()
            return True
        return False

    # ── Coordinate helpers ────────────────────────────────────────────────

    def _clamped_selection(self) -> tuple[float, float, float, float]:
        """Return (x1, y1, x2, y2) in canvas coords, clamped to image bounds."""
        x1 = max(self._disp_x, min(self._sx, self._ex))
        y1 = max(self._disp_y, min(self._sy, self._ey))
        x2 = min(self._disp_x + self._disp_w, max(self._sx, self._ex))
        y2 = min(self._disp_y + self._disp_h, max(self._sy, self._ey))
        return x1, y1, x2, y2

    def _finalise(self):
        """
        Map clamped canvas coordinates back to full image pixel coordinates
        and invoke the on_selected callback.
        """
        x1, y1, x2, y2 = self._clamped_selection()

        ix1 = max(0, min(int((x1 - self._disp_x) / self._disp_scale), self._img_w))
        iy1 = max(0, min(int((y1 - self._disp_y) / self._disp_scale), self._img_h))
        ix2 = max(0, min(int((x2 - self._disp_x) / self._disp_scale), self._img_w))
        iy2 = max(0, min(int((y2 - self._disp_y) / self._disp_scale), self._img_h))

        log.info(
            "Selection finalised: canvas=(%.0f,%.0f)→(%.0f,%.0f)  "
            "image=(%d,%d)→(%d,%d)  size=%dx%d",
            x1, y1, x2, y2, ix1, iy1, ix2, iy2, ix2 - ix1, iy2 - iy1,
        )
        self.close()
        self._on_selected(self._image_path, ix1, iy1, ix2, iy2)
