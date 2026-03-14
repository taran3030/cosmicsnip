"""
Fullscreen selection overlay.

Displays the captured screenshot under a semi-transparent dim layer.
The user drags to select a rectangular region, which is highlighted
in real time. Releasing the mouse finalises the selection and hands
the crop coordinates back to the caller via a callback.

Keyboard:
  Escape — cancel and close.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Gdk, GdkPixbuf
from typing import Callable

from cosmicsnip.config import (
    OVERLAY_DIM_ALPHA,
    SELECTION_BORDER_COLOR,
    SELECTION_BORDER_WIDTH,
    MIN_SELECTION_SIZE,
)


class SelectionOverlay(Gtk.Window):
    """
    A frameless fullscreen window for region selection.

    Args:
        app: The parent Gtk.Application.
        image_path: Filesystem path to the fullscreen capture.
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

        # Load screenshot
        self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        self._img_w = self._pixbuf.get_width()
        self._img_h = self._pixbuf.get_height()

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

    # ── Drawing ──────────────────────────────────────────────────────────

    def _draw(self, _area, cr, w: int, h: int):
        if w == 0 or h == 0:
            return

        kx = w / self._img_w
        ky = h / self._img_h

        # Background screenshot
        cr.save()
        cr.scale(kx, ky)
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()
        cr.restore()

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

        # Bright cutout
        cr.save()
        cr.rectangle(x1, y1, sw, sh)
        cr.clip()
        cr.scale(kx, ky)
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()
        cr.restore()

        # Selection border
        r, g, b, a = SELECTION_BORDER_COLOR
        cr.set_source_rgba(r, g, b, a)
        cr.set_line_width(SELECTION_BORDER_WIDTH)
        cr.rectangle(x1, y1, sw, sh)
        cr.stroke()

        # Dimension badge
        iw, ih = int(sw / kx), int(sh / ky)
        dim = f"{iw} × {ih}"
        cr.set_font_size(12)
        ext = cr.text_extents(dim)
        bx, by = x1, y2 + 8
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
        """Convert screen coords → image coords and invoke callback."""
        alloc = self._canvas.get_allocation()
        if alloc.width == 0 or alloc.height == 0:
            return

        kx = self._img_w / alloc.width
        ky = self._img_h / alloc.height

        x1 = max(0, int(min(self._sx, self._ex) * kx))
        y1 = max(0, int(min(self._sy, self._ey) * ky))
        x2 = min(self._img_w, int(max(self._sx, self._ex) * kx))
        y2 = min(self._img_h, int(max(self._sy, self._ey) * ky))

        self.close()
        self._on_selected(self._image_path, x1, y1, x2, y2)
